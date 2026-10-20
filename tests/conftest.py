import base64
import io
import random
import os
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from server.app import create_app
from server.db import metadata
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@pytest.fixture
def image_data():
    image = Image.new("RGB", (900, 500), "#eeeeee")
    draw = ImageDraw.Draw(image)
    randomizer = random.Random(43)
    for _ in range(160):
        x, y = randomizer.randrange(850), randomizer.randrange(450)
        draw.rectangle(
            (x, y, x + randomizer.randrange(5, 45), y + randomizer.randrange(5, 45)),
            fill=tuple(randomizer.randrange(240) for _ in range(3)),
        )
    draw.text(
        (200, 200), "SYNTHETIC TEST ONLY - Ada Example", fill="black", font_size=32
    )
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@pytest.fixture
def database_url(tmp_path):
    url = os.getenv("PRINT_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    if url.startswith("postgres"):
        if not make_url(url).database.startswith("wdwp_test_"):
            raise RuntimeError(
                "Refusing to reset a database without the wdwp_test_ prefix"
            )
        temporary_engine = create_engine(url)
        metadata.drop_all(temporary_engine)
        temporary_engine.dispose()
    return url


@pytest.fixture
def app(tmp_path, database_url):
    application = create_app(database_url, tmp_path, development=True)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-Print-Client": "web"}) as client:
        yield client


@pytest.fixture
def order(image_data):
    return {
        "id": "order-one",
        "orderNumber": "JOB-001",
        "customer": "Synthetic Studio",
        "widthMm": 90,
        "heightMm": 50,
        "variants": [
            {
                "id": "variant-one",
                "name": "Ada Example",
                "destination": "Bay A",
                "quantity": 100,
                "image": image_data,
            }
        ],
    }


@pytest.fixture
def released(client, order):
    assert client.post("/api/orders", json=order).status_code == 201
    sheet = {
        "number": "SHEET-1",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 100,
        "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
    }
    response = client.post("/api/sheets", json=sheet)
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    assert (
        client.post(
            f"/api/sheets/{identity}/release", json={"key": "release-sheet-1"}
        ).status_code
        == 200
    )
    return client.get("/api/allocations?active=true").json()[0]
