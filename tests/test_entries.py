from unittest.mock import patch


def test_get_entry_missing_returns_404_without_tmdb_call(client):
    with patch("app.routers.entries.get_movie") as get_movie:
        response = client.get("/entry/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Entry not found"}
    get_movie.assert_not_called()


def test_create_entry_rejects_duplicate_tmdb_id(client):
    first = client.post(
        "/entry",
        json={"tmdb_id": 42, "status": "want", "added_by": "mel"},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/entry",
        json={"tmdb_id": 42, "status": "watched", "added_by": "mel"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Entry with this tmdb_id already exists"}
