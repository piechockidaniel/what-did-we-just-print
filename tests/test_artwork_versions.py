import base64
import io
from PIL import Image, ImageDraw


def revised_image(image_data):
    image = Image.open(io.BytesIO(base64.b64decode(image_data.split(",")[1]))).convert(
        "RGB"
    )
    ImageDraw.Draw(image).rectangle((350, 100, 600, 250), fill="blue")
    output = io.BytesIO()
    image.save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def test_revision_preserves_released_and_draft_artwork(client, released, image_data):
    variant = client.get("/api/orders").json()[0]["variants"][0]
    original = variant["artworkId"]
    original_version = variant["artworkVersionId"]
    draft = {
        "number": "BEFORE-REVISION",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 10,
        "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
    }
    draft_id = client.post("/api/sheets", json=draft).json()["id"]
    payload = {
        "image": revised_image(image_data),
        "expectedRevision": 1,
        "key": "artwork-revision-key",
        "reason": "Correct printed name",
    }
    response = client.post("/api/variants/variant-one/artwork", json=payload)
    assert response.status_code == 200, response.text
    assert (
        client.post("/api/variants/variant-one/artwork", json=payload).json()["id"]
        == response.json()["id"]
    )
    current = client.get("/api/orders").json()[0]["variants"][0]
    assert current["artworkRevision"] == 2 and current["artworkId"] != original
    assert client.get("/api/allocations").json()[0]["artwork_id"] == original
    assert client.get("/api/allocations").json()[0]["artworkRevision"] == 1
    assert client.get(f"/api/artworks/{original}").status_code == 200
    before = next(
        sheet for sheet in client.get("/api/sheets").json() if sheet["id"] == draft_id
    )
    assert before["placements"][0]["artworkVersionId"] == original_version
    assert before["artworkImages"][original_version] == f"/api/artworks/{original}"
    assert (
        client.post(
            f"/api/sheets/{draft_id}/release", json={"key": "release-pinned-draft"}
        ).status_code
        == 200
    )
    draft["number"] = "AFTER-REVISION"
    after_id = client.post("/api/sheets", json=draft).json()["id"]
    client.post(f"/api/sheets/{after_id}/release", json={"key": "release-latest-draft"})
    rows = client.get("/api/allocations").json()
    assert (
        next(row for row in rows if row["sheet_id"] == after_id)["artworkRevision"] == 2
    )
    versions = client.get("/api/variants/variant-one/artwork").json()
    assert [v["revision"] for v in versions] == [2, 1]
    exported = client.get("/api/catalog/export").json()
    assert exported["orders"][0]["variants"][0]["image"] == payload["image"]
    assert (
        client.post("/api/catalog/preview", json=exported).json()[0]["status"] == "skip"
    )


def test_stale_identical_and_invalid_revisions_do_not_change_history(
    client, order, image_data
):
    client.post("/api/orders", json=order)
    same = {
        "image": image_data,
        "expectedRevision": 1,
        "key": "same-artwork-key",
        "reason": "No actual change",
    }
    assert (
        client.post("/api/variants/variant-one/artwork", json=same).status_code == 409
    )
    changed = {**same, "image": revised_image(image_data), "key": "new-artwork-key"}
    assert (
        client.post("/api/variants/variant-one/artwork", json=changed).status_code
        == 200
    )
    assert (
        client.post(
            "/api/variants/variant-one/artwork",
            json={**same, "key": "stale-artwork-key"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/variants/variant-one/artwork",
            json={
                **same,
                "image": "data:image/png;base64,bad",
                "key": "bad-artwork-key",
                "expectedRevision": 2,
            },
        ).status_code
        == 422
    )
    assert len(client.get("/api/variants/variant-one/artwork").json()) == 2
    assert len(client.get("/api/jobs").json()) == 2


def test_placement_cannot_bind_another_variants_artwork(client, order):
    other = {**order["variants"][0], "id": "variant-other", "name": "Other variant"}
    order["variants"].append(other)
    client.post("/api/orders", json=order)
    versions = client.get("/api/variants/variant-other/artwork").json()
    sheet = {
        "number": "WRONG-VARIANT",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 1,
        "placements": [
            {
                "variantId": "variant-one",
                "artworkVersionId": versions[0]["id"],
                "x": 0,
                "y": 0,
            }
        ],
    }
    assert client.post("/api/sheets", json=sheet).status_code == 422


def test_mixed_revisions_get_distinct_allocations(client, released, image_data):
    original = client.get("/api/orders").json()[0]["variants"][0]["artworkVersionId"]
    client.post(
        "/api/variants/variant-one/artwork",
        json={
            "image": revised_image(image_data),
            "expectedRevision": 1,
            "key": "mixed-revision-key",
            "reason": "New artwork",
        },
    )
    current = client.get("/api/orders").json()[0]["variants"][0]["artworkVersionId"]
    sheet = {
        "number": "MIXED-REVISIONS",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 10,
        "placements": [
            {"variantId": "variant-one", "artworkVersionId": original, "x": 0, "y": 0},
            {"variantId": "variant-one", "artworkVersionId": current, "x": 90, "y": 0},
        ],
    }
    identity = client.post("/api/sheets", json=sheet).json()["id"]
    assert (
        client.post(
            f"/api/sheets/{identity}/release", json={"key": "mixed-release-key"}
        ).status_code
        == 200
    )
    allocations = [
        r for r in client.get("/api/allocations").json() if r["sheet_id"] == identity
    ]
    assert len(allocations) == 2 and {r["artworkRevision"] for r in allocations} == {
        1,
        2,
    }
    assert all(r["released"] == 10 for r in allocations)
