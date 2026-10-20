import base64
import copy
import io
import time
from PIL import Image
from sqlalchemy import update
from server.db import jobs
from server.worker import run_one, reconcile_cache
from vision.matching import cache_path
from vision.evaluate import evaluate
import json
import pytest


def test_order_retry_and_case_insensitive_duplicate(client, order):
    assert client.post("/api/orders", json=order).status_code == 201
    assert client.post("/api/orders", json=order).json()["existing"] is True
    assert len(client.get("/api/history").json()) == 1
    another = copy.deepcopy(order)
    another["id"] = "another-order"
    another["orderNumber"] = "job-001"
    another["variants"][0]["id"] = "another-variant"
    assert client.post("/api/orders", json=another).status_code == 409


def test_worker_lease_recovery_and_version_rebuild(client, order, app):
    client.post("/api/orders", json=order)
    with app.state.engine.begin() as conn:
        conn.execute(
            update(jobs).values(
                state="running", lease_until=time.time() - 1, attempts=1
            )
        )
    assert run_one(app.state.engine, app.state.data_dir)
    identity = client.get("/api/orders").json()[0]["variants"][0]["artworkId"]
    assert cache_path(app.state.data_dir, identity).is_file()
    # Deleting only a temporary-test cache simulates a changed extractor version.
    cache_path(app.state.data_dir, identity).unlink()
    reconcile_cache(app.state.engine, app.state.data_dir)
    assert client.get("/api/jobs").json()[0]["state"] == "pending"
    assert run_one(app.state.engine, app.state.data_dir)
    assert client.get("/api/jobs").json()[0]["state"] == "ready"


def test_exhausted_worker_and_manual_retry(client, order, app):
    client.post("/api/orders", json=order)
    with app.state.engine.begin() as conn:
        conn.execute(
            update(jobs).values(
                state="running", lease_until=time.time() - 1, attempts=3
            )
        )
    run_one(app.state.engine, app.state.data_dir)
    job = client.get("/api/jobs").json()[0]
    assert job["state"] == "failed"
    assert (
        client.post(
            f"/api/jobs/{job['id']}/retry",
            json={"key": "retry-job-request", "reason": "Worker recovered"},
        ).status_code
        == 200
    )
    assert run_one(app.state.engine, app.state.data_dir)
    assert client.get("/api/jobs").json()[0]["state"] == "ready"


def test_quality_gate_invalid_corners_and_unknown_pool(client, image_data):
    image = Image.new("RGB", (200, 100), "white")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    blank = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    assert (
        client.post("/api/scans", json={"image": blank}).json()["decision"]
        == "insufficient-evidence"
    )
    assert (
        client.post("/api/scans", json={"image": image_data}).json()["decision"]
        == "unknown"
    )
    assert (
        client.post(
            "/api/scans",
            json={
                "image": image_data,
                "corners": [[0, 0], [1000, 0], [800, 400], [0, 400]],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/scans",
            json={"image": image_data, "corners": [[0, 0], [0, 0], [0, 0], [0, 0]]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/scans",
            json={
                "image": image_data,
                "corners": [[0, 0], [899, 0], [899, 499], [0, 499]],
            },
        ).status_code
        == 200
    )


def test_cancel_after_partial_packing_and_reversal(client, released):
    identity = released["id"]
    packing = client.post(
        f"/api/allocations/{identity}/pack",
        json={
            "key": "partial-pack-request",
            "quantity": 30,
            "revision": 1,
            "reason": "Manual inspection",
        },
    ).json()
    assert (
        client.post(
            f"/api/allocations/{identity}/cancel",
            json={"key": "partial-cancel-request", "reason": "Cancel 70 remaining"},
        ).status_code
        == 200
    )
    row = client.get("/api/allocations").json()[0]
    assert row["packed"] == 30 and row["cancelled"] == 70 and row["remaining"] == 0
    assert (
        client.post(
            f"/api/packing/{packing['id']}/reverse",
            json={
                "key": "partial-reverse-request",
                "reason": "Correction reopens only packed portion",
            },
        ).status_code
        == 200
    )
    row = client.get("/api/allocations").json()[0]
    assert row["remaining"] == 30 and row["cancelled"] == 70


def test_evaluation_rejects_reference_leakage(
    client, released, image_data, app, tmp_path
):
    path = tmp_path / "reference.png"
    path.write_bytes(base64.b64decode(image_data.split(",")[1]))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "split": "held-out",
                "captureSession": "synthetic-leakage-check",
                "cases": [
                    {"file": "reference.png", "acceptableVariantIds": ["variant-one"]}
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="reference image"):
        evaluate(app.state.engine, app.state.data_dir, manifest)


def test_new_production_invalidates_old_scan(client, released, image_data, app):
    run_one(app.state.engine, app.state.data_dir)
    scan = client.post("/api/scans", json={"image": image_data}).json()
    assert (
        client.post(
            f"/api/scans/{scan['id']}/review",
            json={
                "allocationId": released["id"],
                "decision": "confirm",
                "reason": "Independent context",
            },
        ).status_code
        == 200
    )
    sheet = client.post(
        "/api/sheets",
        json={
            "number": "NEW-POOL-SHEET",
            "widthMm": 320,
            "heightMm": 450,
            "impressions": 1,
            "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
        },
    ).json()
    client.post(
        f"/api/sheets/{sheet['id']}/release", json={"key": "new-pool-release-key"}
    )
    assert (
        client.post(
            f"/api/allocations/{released['id']}/pack",
            json={
                "key": "new-pool-pack-key",
                "revision": 1,
                "quantity": 1,
                "scanId": scan["id"],
                "reason": "Old scan",
            },
        ).status_code
        == 409
    )


def test_station_filter_is_explicit_and_does_not_infer_size(
    client, released, image_data, app
):
    run_one(app.state.engine, app.state.data_dir)
    station = client.post(
        "/api/stations",
        json={
            "name": "Small product station",
            "maxWidthMm": 40,
            "maxHeightMm": 40,
            "notes": "Synthetic API filter test; not calibrated",
        },
    ).json()
    assert client.get("/api/stations").json()[0]["id"] == station["id"]
    scan = client.post(
        "/api/scans", json={"image": image_data, "stationId": station["id"]}
    ).json()
    assert scan["activeAllocations"] == 0
    assert scan["candidates"] == []
    assert "not established" in scan["stationSizing"]
    assert (
        client.post(
            "/api/scans", json={"image": image_data, "stationId": "not-real"}
        ).status_code
        == 404
    )
