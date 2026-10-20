import json
from scripts.generate_print_kit import generate


def test_synthetic_kit_import_and_release_preserve_ambiguity(client, tmp_path):
    destination = tmp_path / "print-kit"
    result = generate(destination)
    assert result["physicalCapturesCreated"] == 0
    catalog = json.loads((destination / "catalog.json").read_text())
    assert client.post("/api/catalog/preview", json=catalog).status_code == 200
    assert client.post("/api/catalog/import", json=catalog).json()["imported"] == 2
    for index in range(6):
        sheet = json.loads((destination / f"sheet-{index + 1}.json").read_text())
        response = client.post("/api/sheets", json=sheet)
        assert response.status_code == 201, response.text
        assert (
            client.post(
                f"/api/sheets/{response.json()['id']}/release",
                json={"key": f"kit-release-{index}"},
            ).status_code
            == 200
        )
    rows = client.get("/api/allocations?active=true").json()
    assert len(rows) == 51
    assert len({row["artwork_id"] for row in rows}) == 50
    assert len(client.get("/api/jobs").json()) == 50
