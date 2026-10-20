from concurrent.futures import ThreadPoolExecutor
import copy
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from server.db import artworks, jobs, users
from server.auth import password_hash
from server.app import create_app
from server.worker import run_one


def pack(client, allocation, quantity, key=None, **extra):
    return client.post(
        f"/api/allocations/{allocation['id']}/pack",
        json={
            "key": key or str(uuid4()),
            "revision": allocation["revision"],
            "quantity": quantity,
            "reason": "Independent manual identification",
            **extra,
        },
    )


def test_shared_catalog_and_import(client, app, order):
    report = client.post(
        "/api/catalog/preview", json={"schemaVersion": 1, "orders": [order]}
    )
    assert report.json()[0]["status"] == "new"
    assert (
        client.post(
            "/api/catalog/import", json={"schemaVersion": 1, "orders": [order]}
        ).json()["imported"]
        == 1
    )
    with TestClient(app, headers={"X-Print-Client": "web"}) as second:
        assert second.get("/api/orders").json()[0]["variants"][0]["id"] == "variant-one"
    exported = client.get("/api/catalog/export").json()
    assert (
        exported["orders"][0]["variants"][0]["image"] == order["variants"][0]["image"]
    )
    assert client.post("/api/catalog/import", json=exported).json() == {
        "imported": 0,
        "skipped": 1,
    }
    changed = copy.deepcopy(order)
    changed["variants"][0]["destination"] = "Different bay"
    assert (
        client.post(
            "/api/catalog/import", json={"schemaVersion": 1, "orders": [changed]}
        ).status_code
        == 409
    )


def test_partial_complete_reverse_idempotency(client, released):
    first = pack(client, released, 40, "packing-request-1")
    assert first.status_code == 200, first.text
    assert (
        pack(client, released, 40, "packing-request-1").json()["id"]
        == first.json()["id"]
    )
    assert pack(client, released, 30, "packing-request-1").status_code == 409
    assert pack(client, released, 1).status_code == 409  # stale revision
    active = client.get("/api/allocations?active=true").json()[0]
    assert active["remaining"] == 60
    assert pack(client, active, 61).status_code == 409
    assert pack(client, active, 60).status_code == 200
    assert client.get("/api/allocations?active=true").json() == []
    reverse = client.post(
        f"/api/packing/{first.json()['id']}/reverse",
        json={"key": "reverse-request-1", "reason": "Packing correction"},
    )
    assert reverse.status_code == 200
    assert client.get("/api/allocations?active=true").json()[0]["remaining"] == 40
    assert (
        client.post(
            f"/api/packing/{first.json()['id']}/reverse",
            json={"key": "reverse-request-2", "reason": "Again"},
        ).status_code
        == 409
    )


def test_concurrent_operators_cannot_overpack(client, app, released):
    def attempt(_):
        with TestClient(app, headers={"X-Print-Client": "web"}) as other:
            return pack(other, released, 60).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert sorted(statuses) == [200, 409]
    assert client.get("/api/allocations?active=true").json()[0]["remaining"] == 40


def test_sheet_geometry_and_repeated_placements(client, order):
    client.post("/api/orders", json=order)
    body = {
        "number": "GEOMETRY",
        "widthMm": 180,
        "heightMm": 50,
        "impressions": 50,
        "placements": [
            {"variantId": "variant-one", "x": 0, "y": 0},
            {"variantId": "variant-one", "x": 90, "y": 0},
        ],
    }
    overlap = copy.deepcopy(body)
    overlap["placements"][1]["x"] = 89
    assert client.post("/api/sheets", json=overlap).status_code == 422
    outside = copy.deepcopy(body)
    outside["placements"][1]["x"] = 91
    assert client.post("/api/sheets", json=outside).status_code == 422
    identity = client.post("/api/sheets", json=body).json()["id"]
    assert (
        client.post(
            f"/api/sheets/{identity}/release", json={"key": "release-repeat-1"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/sheets/{identity}/release", json={"key": "release-repeat-1"}
        ).status_code
        == 200
    )
    assert len(client.get("/api/allocations").json()) == 1
    assert client.get("/api/allocations").json()[0]["released"] == 100


def test_shared_artwork_cancel_and_reprint(client, order, released, app):
    second = copy.deepcopy(order)
    second["id"] = "order-two"
    second["orderNumber"] = "JOB-002"
    second["variants"][0]["id"] = "variant-two"
    assert client.post("/api/orders", json=second).status_code == 201
    body = {
        "number": "SECOND-SHEET",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 25,
        "placements": [{"variantId": "variant-two", "x": 0, "y": 0}],
    }
    identity = client.post("/api/sheets", json=body).json()["id"]
    client.post(f"/api/sheets/{identity}/release", json={"key": "release-shared-1"})
    with app.state.engine.connect() as conn:
        assert len(conn.execute(select(artworks)).all()) == 1
        assert len(conn.execute(select(jobs)).all()) == 1
    assert (
        client.post(
            f"/api/allocations/{released['id']}/cancel",
            json={"key": "cancel-request-1", "reason": "Job cancelled"},
        ).status_code
        == 200
    )
    active = client.get("/api/allocations?active=true").json()
    assert len(active) == 1 and active[0]["variant_id"] == "variant-two"
    body["number"] = "REPRINT-1"
    body["placements"][0]["variantId"] = "variant-one"
    identity = client.post("/api/sheets", json=body).json()["id"]
    client.post(f"/api/sheets/{identity}/release", json={"key": "release-reprint-1"})
    assert len(client.get("/api/allocations?active=true").json()) == 2


def test_invalid_images_and_atomic_import(client, order):
    bad = copy.deepcopy(order)
    bad["id"] = "bad-order"
    bad["orderNumber"] = "BAD"
    bad["variants"][0]["id"] = "bad-variant"
    bad["variants"][0]["image"] = "data:image/png;base64,AAA="
    assert client.post("/api/orders", json=bad).status_code == 422
    assert (
        client.post(
            "/api/catalog/import", json={"schemaVersion": 1, "orders": [order, bad]}
        ).status_code
        == 422
    )
    assert client.get("/api/orders").json() == []


def test_worker_and_scan_ambiguity_stale_review(client, order, released, app):
    assert run_one(app.state.engine, app.state.data_dir)
    assert not run_one(app.state.engine, app.state.data_dir)
    assert client.get("/api/jobs").json()[0]["state"] == "ready"
    # Another live allocation with identical visible artwork must remain a candidate.
    body = {
        "number": "IDENTICAL",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 20,
        "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
    }
    sheet_id = client.post("/api/sheets", json=body).json()["id"]
    client.post(f"/api/sheets/{sheet_id}/release", json={"key": "release-identical-1"})
    response = client.post("/api/scans", json={"image": order["variants"][0]["image"]})
    assert response.status_code == 200, response.text
    scan = response.json()
    assert scan["decision"] == "ambiguous"
    assert len(scan["candidates"]) == 2
    assert scan["candidates"][0]["inliers"] >= 12
    assert pack(client, released, 1, scanId=scan["id"]).status_code == 409
    assert (
        client.post(
            f"/api/scans/{scan['id']}/review",
            json={
                "allocationId": released["id"],
                "decision": "confirm",
                "reason": "Independent batch context",
            },
        ).status_code
        == 200
    )
    assert pack(client, released, 1, scanId=scan["id"]).status_code == 200
    assert (
        client.post(
            f"/api/scans/{scan['id']}/review",
            json={
                "allocationId": released["id"],
                "decision": "confirm",
                "reason": "Stale scan",
            },
        ).status_code
        == 409
    )


def test_auth_roles_origin_and_upload_guard(tmp_path, order):
    app = create_app(f"sqlite:///{tmp_path / 'auth.db'}", tmp_path, development=False)
    with app.state.engine.begin() as conn:
        conn.execute(
            users.insert().values(
                name="operator",
                password=password_hash("test-password-only"),
                role="operator",
            )
        )
    with TestClient(
        app, base_url="https://testserver", headers={"X-Print-Client": "web"}
    ) as client:
        assert client.get("/api/orders").status_code == 401
        assert (
            client.post(
                "/api/login", json={"name": "operator", "password": "wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/login",
                json={"name": "operator", "password": "test-password-only"},
            ).status_code
            == 200
        )
        assert client.get("/api/session").json()["role"] == "operator"
        assert (
            client.post(
                "/api/orders",
                json=order,
                headers={"Origin": "https://unrelated.example"},
            ).status_code
            == 403
        )
        assert client.post("/api/orders", json=order).status_code == 201
        assert (
            client.post(
                "/api/allocations/not-real/cancel",
                json={"key": "cancel-request-1", "reason": "No access"},
            ).status_code
            == 403
        )
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/orders").status_code == 401


def test_import_duplicate_ids_in_file(client, order):
    response = client.post(
        "/api/catalog/preview", json={"schemaVersion": 1, "orders": [order, order]}
    )
    assert response.status_code == 200
    assert response.json()[1]["status"] == "conflict"
    assert (
        client.post(
            "/api/catalog/import", json={"schemaVersion": 1, "orders": [order, order]}
        ).status_code
        == 409
    )
    assert client.get("/api/orders").json() == []
