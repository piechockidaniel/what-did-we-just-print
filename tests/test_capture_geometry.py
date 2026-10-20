import base64
import io
from PIL import Image
from server.worker import run_one


def encode(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_automatic_boundary_and_rotation_are_experimental(
    client, released, image_data, app
):
    run_one(app.state.engine, app.state.data_dir)
    card = Image.open(io.BytesIO(base64.b64decode(image_data.split(",")[1]))).convert(
        "RGB"
    )
    photograph = Image.new("RGB", (1300, 900), "#151515")
    photograph.paste(card, (200, 200))
    result = client.post(
        "/api/scans", json={"image": encode(photograph), "autoCrop": True}
    )
    assert result.status_code == 200, result.text
    result = result.json()
    assert result["framing"]["mode"] == "auto-experimental"
    assert len(result["framing"]["corners"]) == 4
    assert result["candidates"][0]["variant_id"] == "variant-one"
    assert result["candidates"][0]["inliers"] > 40
    assert result["decision"] == "review-required"
    rotated = client.post(
        "/api/scans", json={"image": encode(card.rotate(90, expand=True))}
    ).json()
    assert rotated["candidates"][0]["inliers"] > 40
    assert rotated["decision"] == "review-required"
