import threading
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Watchlist, WatchlistStatus


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.themoviedb.org/3/movie/0")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("TMDB error", request=request, response=response)


def _timeout_error() -> httpx.TimeoutException:
    return httpx.TimeoutException(
        "timed out",
        request=httpx.Request("GET", "https://api.themoviedb.org/3/movie/0"),
    )


def _request_error() -> httpx.RequestError:
    return httpx.RequestError(
        "connection failed",
        request=httpx.Request("GET", "https://api.themoviedb.org/3/movie/0"),
    )


def test_search_merges_pages_and_sorts_by_popularity(client):
    page1 = {
        "page": 1,
        "total_pages": 5,
        "total_results": 87,
        "results": [
            {"id": 1, "title": "Bat Food", "popularity": 5.0},
            {"id": 2, "title": "Battle", "popularity": 20.0},
        ],
    }
    page2 = {
        "page": 2,
        "total_pages": 5,
        "total_results": 87,
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
    body = response.json()
    titles = [movie["title"] for movie in body["results"]]
    assert titles == ["Batman", "Battle", "Bat Food"]
    assert body["page"] == 1
    assert body["total_pages"] == 1
    assert body["total_results"] == 87


def test_search_falls_back_to_page1_when_page2_fails(client):
    page1 = {
        "page": 1,
        "total_pages": 2,
        "total_results": 40,
        "results": [{"id": 1, "title": "Only Page One", "popularity": 10.0}],
    }

    def fake_cached_get(path, params=None):
        page = (params or {}).get("page", "1")
        if page == "2":
            raise _http_error(500)
        return page1

    with patch("app.tmdb._cached_get", side_effect=fake_cached_get):
        response = client.get("/search/movie", params={"query": "bat"})

    assert response.status_code == 200
    assert [movie["title"] for movie in response.json()["results"]] == ["Only Page One"]


def test_search_rejects_empty_query(client):
    response = client.get("/search/movie", params={"query": ""})
    assert response.status_code == 422


def test_search_rejects_whitespace_only_query(client):
    response = client.get("/search/movie", params={"query": "   "})
    assert response.status_code == 422


def test_get_upcoming_movies_uses_us_region(client):
    payload = {"results": [{"id": 10, "title": "Soon"}]}

    with patch("app.tmdb._cached_get", return_value=payload) as cached_get:
        response = client.get("/movies/upcoming")

    assert response.status_code == 200
    assert response.json() == payload
    cached_get.assert_called_once_with("/movie/upcoming", params={"region": "US"})


@pytest.mark.parametrize("upstream_status", [401, 404, 429, 500, 503])
def test_get_upcoming_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_upcoming_movies", side_effect=_http_error(upstream_status)):
        response = client.get("/movies/upcoming")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_upcoming_timeout_returns_503(client):
    with patch("app.tmdb.get_upcoming_movies", side_effect=_timeout_error()):
        response = client.get("/movies/upcoming")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_upcoming_connection_error_returns_503(client):
    with patch("app.tmdb.get_upcoming_movies", side_effect=_request_error()):
        response = client.get("/movies/upcoming")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_movie_unknown_id_returns_404(client):
    with patch("app.tmdb.get_movie", side_effect=_http_error(404)):
        response = client.get("/movies/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Movie not found"


@pytest.mark.parametrize("upstream_status", [401, 429, 500, 503])
def test_get_movie_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_movie", side_effect=_http_error(upstream_status)):
        response = client.get("/movies/999999999")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_movie_timeout_returns_503(client):
    with patch("app.tmdb.get_movie", side_effect=_timeout_error()):
        response = client.get("/movies/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_movie_request_error_returns_503(client):
    with patch("app.tmdb.get_movie", side_effect=_request_error()):
        response = client.get("/movies/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


@pytest.mark.parametrize("upstream_status", [401, 429, 503])
def test_search_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.search_movies", side_effect=_http_error(upstream_status)):
        response = client.get("/search/movie", params={"query": "bat"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_search_tmdb_404_returns_503(client):
    with patch("app.tmdb.search_movies", side_effect=_http_error(404)):
        response = client.get("/search/movie", params={"query": "bat"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


@pytest.mark.parametrize("upstream_status", [401, 429, 503])
def test_trending_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_trending_movies", side_effect=_http_error(upstream_status)):
        response = client.get("/trending/movies")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_entry_missing_returns_404_without_tmdb_call(client):
    with patch("app.routers.entries.get_movie") as mock_get_movie:
        response = client.get("/entry/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"
    mock_get_movie.assert_not_called()


def test_get_entry_returns_503_when_tmdb_fails(client):
    created = client.post(
        "/entry",
        json={"tmdb_id": 55, "status": "want", "added_by": "mel"},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]

    with patch("app.routers.entries.get_movie", side_effect=_http_error(503)):
        response = client.get(f"/entry/{entry_id}")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_entry_returns_404_when_tmdb_movie_missing(client):
    created = client.post(
        "/entry",
        json={"tmdb_id": 56, "status": "want", "added_by": "mel"},
    )
    entry_id = created.json()["id"]

    with patch("app.routers.entries.get_movie", side_effect=_http_error(404)):
        response = client.get(f"/entry/{entry_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Movie not found"


def test_create_entry_rejects_duplicate_tmdb_id(client, engine):
    first = client.post(
        "/entry",
        json={"tmdb_id": 42, "status": "want", "added_by": "mel"},
    )
    assert first.status_code == 201
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


def test_create_entry_concurrent_duplicate_posts(tmp_path):
    # File DB gives each thread its own connection. StaticPool cannot do that.
    eng = create_engine(
        f"sqlite:///{tmp_path / 'race.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)

    barrier = threading.Barrier(2)
    results: list[int] = []
    lock = threading.Lock()

    def insert_once():
        barrier.wait(timeout=5)
        with Session(eng) as session:
            existing = session.exec(select(Watchlist).where(Watchlist.tmdb_id == 77)).first()
            if existing is not None:
                with lock:
                    results.append(409)
                return
            session.add(Watchlist(tmdb_id=77, status=WatchlistStatus.WANT, added_by="race"))
            try:
                session.commit()
                status = 200
            except IntegrityError:
                session.rollback()
                status = 409
            with lock:
                results.append(status)

    threads = [threading.Thread(target=insert_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == [200, 409]
    with Session(eng) as session:
        rows = session.exec(select(Watchlist).where(Watchlist.tmdb_id == 77)).all()
        assert len(rows) == 1


def test_create_entry_integrity_error_returns_409(client, engine):
    with Session(engine) as session:
        session.add(Watchlist(tmdb_id=88, status=WatchlistStatus.WANT, added_by="seed"))
        session.commit()

    # Pretend the pre-check missed the row so commit hits the unique index.
    with patch("sqlmodel.Session.exec") as mock_exec:
        mock_exec.return_value.first.return_value = None
        response = client.post(
            "/entry",
            json={"tmdb_id": 88, "status": "want", "added_by": "race"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Entry with this tmdb_id already exists"
