import pytest
from sqlalchemy import select, update, inspect
from server.db import (
    make_engine,
    orders,
    variants,
    artworks,
    allocations,
    sheets,
    schema_versions,
)
from server.migrations import upgrade, downgrade, current
from server.storage import store_image
from server.app import create_app
from fastapi.testclient import TestClient


def v1_database(tmp_path, image_data, url):
    engine = make_engine(url, initialize=False)
    upgrade(engine, 1)
    artwork = store_image(tmp_path, image_data)
    with engine.begin() as conn:
        conn.execute(artworks.insert().values(**artwork, state="pending"))
        conn.execute(
            orders.insert().values(
                id="o1",
                number="LEGACY",
                customer="Legacy fixture",
                width=90,
                height=50,
                created="2026-10-20T00:00:00+00:00",
            )
        )
        conn.execute(
            variants.insert().values(
                id="v1",
                order_id="o1",
                artwork_id=artwork["id"],
                name="Original",
                destination="Bay A",
                quantity=100,
                side="front",
            )
        )
        conn.execute(
            sheets.insert().values(
                id="s1",
                number="LEGACY-SHEET",
                width=320,
                height=450,
                impressions=100,
                state="released",
                placements=[
                    {"variantId": "v1", "x": 0, "y": 0, "rotation": 0, "side": "front"}
                ],
                created="2026-10-20T00:00:00+00:00",
            )
        )
        conn.execute(
            allocations.insert().values(
                id="a1",
                sheet_id="s1",
                variant_id="v1",
                released=100,
                packed=37,
                cancelled=0,
                revision=2,
            )
        )
    return url, engine, artwork


def test_upgrade_preserves_existing_quantities_and_original_images(
    tmp_path, image_data, database_url
):
    url, engine, artwork = v1_database(tmp_path, image_data, database_url)
    assert upgrade(engine) == 2
    assert upgrade(engine) == 2
    engine.dispose()
    app = create_app(url, tmp_path, development=True)
    with TestClient(app, headers={"X-Print-Client": "web"}) as client:
        allocation = client.get("/api/allocations").json()[0]
        assert (
            allocation["artwork_id"] == artwork["id"]
            and allocation["artworkRevision"] == 1
        )
        assert allocation["packed"] == 37 and allocation["remaining"] == 63
        assert (
            client.get("/api/orders").json()[0]["variants"][0]["artworkRevision"] == 1
        )
        assert client.get(f"/api/artworks/{artwork['id']}").status_code == 200
    app.state.engine.dispose()


def test_safe_downgrade_and_reupgrade(tmp_path, image_data, database_url):
    _, engine, _ = v1_database(tmp_path, image_data, database_url)
    upgrade(engine)
    assert downgrade(engine) == 1
    with engine.connect() as conn:
        assert current(conn) == 1
        assert not inspect(conn).has_table("artwork_versions")
        assert (
            "artworkVersionId"
            not in conn.execute(select(sheets.c.placements)).scalar_one()[0]
        )
    assert upgrade(engine) == 2
    engine.dispose()


def test_downgrade_refuses_to_discard_revision_bindings(
    client, released, image_data, app
):
    from tests.test_artwork_versions import revised_image

    assert (
        client.post(
            "/api/variants/variant-one/artwork",
            json={
                "image": revised_image(image_data),
                "expectedRevision": 1,
                "key": "migration-revision-key",
                "reason": "Actual revision",
            },
        ).status_code
        == 200
    )
    with pytest.raises(RuntimeError, match="revisions exist"):
        downgrade(app.state.engine)
    with app.state.engine.connect() as conn:
        assert current(conn) == 2
    assert client.get("/api/allocations").json()[0]["artworkRevision"] == 1


def test_unknown_schema_is_rejected_before_changes(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'unknown.db'}", initialize=False)
    upgrade(engine, 1)
    with engine.begin() as conn:
        conn.execute(update(schema_versions).values(version=99))
    with pytest.raises(RuntimeError, match="Unsupported schema"):
        upgrade(engine)
    with engine.connect() as conn:
        assert current(conn) == 99 and not inspect(conn).has_table("artwork_versions")
    engine.dispose()


def test_failed_upgrade_rolls_back_schema_and_data(tmp_path, image_data, database_url):
    _, engine, _ = v1_database(tmp_path, image_data, database_url)
    with engine.begin() as conn:
        conn.execute(
            update(sheets)
            .where(sheets.c.id == "s1")
            .values(placements=[{"variantId": "missing-legacy-variant"}])
        )
    with pytest.raises(KeyError):
        upgrade(engine)
    with engine.connect() as conn:
        assert current(conn) == 1
        assert not inspect(conn).has_table("artwork_versions")
        assert conn.execute(select(allocations.c.packed)).scalar_one() == 37
    engine.dispose()
