import copy


def draft(client, order):
    assert client.post("/api/orders", json=order).status_code == 201
    body = {
        "number": "EDITABLE-SHEET",
        "widthMm": 320,
        "heightMm": 450,
        "impressions": 100,
        "placements": [{"variantId": "variant-one", "x": 0, "y": 0}],
    }
    identity = client.post("/api/sheets", json=body).json()["id"]
    return identity, body


def test_edit_draft_and_release_reviewed_revision(client, order):
    identity, original = draft(client, order)
    assert client.get("/api/sheets").json()[0]["revision"] == 1
    changed = {
        **original,
        "impressions": 45,
        "key": "sheet-edit-request",
        "expectedRevision": 1,
    }
    response = client.put(f"/api/sheets/{identity}", json=changed)
    assert response.status_code == 200, response.text
    assert (
        client.put(f"/api/sheets/{identity}", json=changed).json()["id"]
        == response.json()["id"]
    )
    updated = client.get("/api/sheets").json()[0]
    assert updated["impressions"] == 45 and updated["revision"] == 2
    assert (
        client.post(
            f"/api/sheets/{identity}/release",
            json={"key": "stale-release-key", "expectedRevision": 1},
        ).status_code
        == 409
    )
    assert client.get("/api/allocations").json() == []
    assert (
        client.post(
            f"/api/sheets/{identity}/release",
            json={"key": "reviewed-release-key", "expectedRevision": 2},
        ).status_code
        == 200
    )
    assert client.get("/api/allocations").json()[0]["released"] == 45
    assert (
        client.put(
            f"/api/sheets/{identity}",
            json={**changed, "key": "after-release-edit", "expectedRevision": 2},
        ).status_code
        == 409
    )


def test_stale_or_invalid_edit_never_changes_draft(client, order):
    identity, original = draft(client, order)
    invalid = copy.deepcopy(original)
    invalid["placements"][0]["x"] = 319
    assert (
        client.put(
            f"/api/sheets/{identity}",
            json={**invalid, "key": "invalid-edit-key", "expectedRevision": 1},
        ).status_code
        == 422
    )
    assert client.get("/api/sheets").json()[0]["revision"] == 1
    assert (
        client.put(
            f"/api/sheets/{identity}",
            json={
                **original,
                "impressions": 20,
                "key": "first-editor-key",
                "expectedRevision": 1,
            },
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/api/sheets/{identity}",
            json={
                **original,
                "impressions": 30,
                "key": "stale-editor-key",
                "expectedRevision": 1,
            },
        ).status_code
        == 409
    )
    assert client.get("/api/sheets").json()[0]["impressions"] == 20


def test_edit_rejects_duplicate_sheet_number(client, order):
    identity, original = draft(client, order)
    assert (
        client.post(
            "/api/sheets", json={**original, "number": "OTHER-SHEET"}
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/api/sheets/{identity}",
            json={
                **original,
                "number": "other-sheet",
                "key": "duplicate-number-key",
                "expectedRevision": 1,
            },
        ).status_code
        == 409
    )
    current = next(
        row for row in client.get("/api/sheets").json() if row["id"] == identity
    )
    assert current["number"] == "EDITABLE-SHEET" and current["revision"] == 1
