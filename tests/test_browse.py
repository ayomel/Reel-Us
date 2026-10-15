from unittest.mock import patch

import httpx


def test_search_movie_merges_pages_and_sorts_by_popularity(client):
    page1 = {
        "page": 1,
        "total_pages": 2,
        "total_results": 3,
        "results": [
            {"id": 1, "title": "Battle", "popularity": 10.0},
            {"id": 2, "title": "Batwoman", "popularity": 5.0},
        ],
    }
    page2 = {
        "page": 2,
        "total_pages": 2,
        "total_results": 3,
        "results": [
            {"id": 3, "title": "Batman", "popularity": 90.0},
        ],
    }

    def fake_cached_get(path, params=None):
        assert path == "/search/movie"
        assert params["query"] == "bat"
        if params.get("page") == "1":
            return page1
        if params.get("page") == "2":
            return page2
        raise AssertionError(f"unexpected page {params}")

    with patch("app.tmdb._cached_get", side_effect=fake_cached_get):
        response = client.get("/search/movie", params={"query": "bat"})

    assert response.status_code == 200
    titles = [movie["title"] for movie in response.json()["results"]]
    assert titles == ["Batman", "Battle", "Batwoman"]


def test_get_movie_unknown_id_returns_clean_404(client):
    request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/999999")
    response_404 = httpx.Response(404, request=request)

    with patch(
        "app.tmdb.get_movie",
        side_effect=httpx.HTTPStatusError("not found", request=request, response=response_404),
    ):
        response = client.get("/movies/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}


def test_get_movie_tmdb_401_maps_to_clean_404(client):
    request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/999999")
    response_401 = httpx.Response(401, request=request)

    with patch(
        "app.tmdb.get_movie",
        side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response_401),
    ):
        response = client.get("/movies/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}


def test_get_upcoming_movies_uses_us_region_cache_path(client):
    payload = {"results": [{"id": 10, "title": "Soon"}]}

    with patch("app.tmdb._cached_get", return_value=payload) as cached_get:
        response = client.get("/movies/upcoming")

    assert response.status_code == 200
    assert response.json() == payload
    cached_get.assert_called_once_with("/movie/upcoming", params={"region": "US"})
