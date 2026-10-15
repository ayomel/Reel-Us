from unittest.mock import patch

import httpx
import pytest
from sqlmodel import Session, select

from app.models import Watchlist


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/0")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("TMDB error", request=request, response=response)


def test_search_merges_pages_and_sorts_by_popularity(client):
    page1 = {
        "page": 1,
        "total_pages": 2,
        "total_results": 3,
        "results": [
            {"id": 1, "title": "Bat Food", "popularity": 5.0},
            {"id": 2, "title": "Battle", "popularity": 20.0},
        ],
    }
    page2 = {
        "page": 2,
        "total_pages": 2,
        "total_results": 3,
        "results": [
            {"id": 3, "title": "Batman", "popularity": 100.0},
        ],
    }

    def fake_cached_get(path, params=None):
        assert path == "/search/movie"
        page = (params or {}).get("page", "1")
        return page1 if page == "1" else page2

    with patch("app.tmdb._cached_get", side_effect=fake_cached_get):
        response = client.get("/search/movie", params={"query": "bat"})

    assert response.status_code == 200
    titles = [movie["title"] for movie in response.json()["results"]]
    assert titles == ["Batman", "Battle", "Bat Food"]


def test_get_movie_unknown_id_returns_clean_404(client):
    with patch("app.tmdb.get_movie", side_effect=_http_error(404)):
        response = client.get("/movies/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Movie not found"


@pytest.mark.parametrize("upstream_status", [401, 500])
def test_get_movie_maps_upstream_auth_and_server_errors_to_404(client, upstream_status):
    # Unknown/unavailable movie lookups must not leak TMDB 401/500 to clients.
    with patch("app.tmdb.get_movie", side_effect=_http_error(upstream_status)):
        response = client.get("/movies/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Movie not found"


def test_get_entry_missing_returns_404_without_tmdb_call(client):
    with patch("app.routers.entries.get_movie") as mock_get_movie:
        response = client.get("/entry/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"
    mock_get_movie.assert_not_called()


def test_create_entry_rejects_duplicate_tmdb_id(client, engine):
    first = client.post(
        "/entry",
        json={"tmdb_id": 42, "status": "want", "added_by": "mel"},
    )
    assert first.status_code == 200
    assert first.json()["tmdb_id"] == 42

    duplicate = client.post(
        "/entry",
        json={"tmdb_id": 42, "status": "want", "added_by": "mel"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Entry with this tmdb_id already exists"

    with Session(engine) as session:
        rows = session.exec(select(Watchlist).where(Watchlist.tmdb_id == 42)).all()
        assert len(rows) == 1
