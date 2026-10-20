from fastapi.testclient import TestClient
from server.app import create_app
from server.backup import snapshot, restore, verify
import pytest


def test_self_contained_backup_restore_and_corruption(tmp_path, order):
    live = tmp_path / "live"
    live.mkdir()
    app = create_app(f"sqlite:///{live / 'production.db'}", live, development=True)
    with TestClient(app, headers={"X-Print-Client": "web"}) as client:
        assert client.post("/api/orders", json=order).status_code == 201
    app.state.engine.dispose()
    backup = tmp_path / "snapshot"
    manifest = snapshot(live, backup)
    assert len(manifest["files"]) >= 2
    restored = tmp_path / "restored"
    restore(backup, restored)
    # The restored service must read its own artwork, never the original absolute location.
    original_file = next((live / "artwork").iterdir())
    original_file.rename(original_file.with_suffix(".unavailable"))
    recovered = create_app(
        f"sqlite:///{restored / 'production.db'}", restored, development=True
    )
    with TestClient(recovered, headers={"X-Print-Client": "web"}) as client:
        exported = client.get("/api/catalog/export")
        assert exported.status_code == 200
        assert (
            exported.json()["orders"][0]["variants"][0]["image"]
            == order["variants"][0]["image"]
        )
        url = client.get("/api/orders").json()[0]["variants"][0]["image"]
        assert client.get(url).status_code == 200
    recovered.state.engine.dispose()
    artwork = next((backup / "artwork").iterdir())
    artwork.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="altered"):
        verify(backup)


def test_restore_preserves_current_and_released_artwork_versions(
    tmp_path, order, image_data
):
    from tests.test_artwork_versions import revised_image

    root = tmp_path / "revision-live"
    root.mkdir()
    app = create_app(f"sqlite:///{root / 'production.db'}", root, development=True)
    with TestClient(app, headers={"X-Print-Client": "web"}) as client:
        client.post("/api/orders", json=order)
        sheet = client.post(
            "/api/sheets",
            json={
                "number": "REVISION-BACKUP",
                "widthMm": 320,
                "heightMm": 450,
                "impressions": 100,
                "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
            },
        ).json()
        client.post(
            f"/api/sheets/{sheet['id']}/release",
            json={"key": "revision-backup-release"},
        )
        original = client.get("/api/allocations").json()[0]["artwork_id"]
        assert (
            client.post(
                "/api/variants/variant-one/artwork",
                json={
                    "image": revised_image(image_data),
                    "expectedRevision": 1,
                    "key": "revision-backup-change",
                    "reason": "New artwork before backup",
                },
            ).status_code
            == 200
        )
    app.state.engine.dispose()
    backup = tmp_path / "revision-backup"
    snapshot(root, backup)
    target = tmp_path / "revision-restored"
    restore(backup, target)
    recovered = create_app(
        f"sqlite:///{target / 'production.db'}", target, development=True
    )
    with TestClient(recovered, headers={"X-Print-Client": "web"}) as client:
        assert (
            client.get("/api/orders").json()[0]["variants"][0]["artworkRevision"] == 2
        )
        assert client.get("/api/allocations").json()[0]["artwork_id"] == original
        assert client.get("/api/allocations").json()[0]["artworkRevision"] == 1
        versions = client.get("/api/variants/variant-one/artwork").json()
        assert len(versions) == 2 and all(
            client.get(v["image"]).status_code == 200 for v in versions
        )
    recovered.state.engine.dispose()
