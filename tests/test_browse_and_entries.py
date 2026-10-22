import threading
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

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


def test_search_merges_pages_filters_people_deduplicates_and_sorts(client):
    page1 = {
        "page": 1,
        "total_pages": 5,
        "total_results": 87,
        "results": [
            {"id": 1, "media_type": "movie", "title": "Bat Food", "popularity": 5.0},
            {"id": 2, "media_type": "tv", "name": "Battle", "popularity": 20.0},
            {"id": 9, "media_type": "person", "name": "Bat Person", "popularity": 500.0},
        ],
    }
    page2 = {
        "page": 2,
        "total_pages": 5,
        "total_results": 87,
        "results": [
            {"id": 3, "media_type": "movie", "title": "Batman", "popularity": 100.0},
            {"id": 1, "media_type": "movie", "title": "Bat Food duplicate", "popularity": 1.0},
            {"id": 1, "media_type": "tv", "name": "Bat Food show", "popularity": 8.0},
        ],
    }

    def fake_cached_get(path, params=None):
        assert path == "/search/multi"
        page = (params or {}).get("page", "1")
        return page1 if page == "1" else page2

    with patch("app.tmdb._cached_get", side_effect=fake_cached_get):
        response = client.get("/search", params={"query": "bat"})

    assert response.status_code == 200
    body = response.json()
    titles = [item.get("title", item.get("name")) for item in body["results"]]
    assert titles == ["Batman", "Battle", "Bat Food show", "Bat Food"]
    assert body["page"] == 1
    assert body["total_pages"] == 1
    assert body["total_results"] == 4


def test_search_falls_back_to_page1_when_page2_fails(client):
    page1 = {
        "page": 1,
        "total_pages": 2,
        "total_results": 40,
        "results": [
            {
                "id": 1,
                "media_type": "movie",
                "title": "Only Page One",
                "popularity": 10.0,
            }
        ],
    }

    def fake_cached_get(path, params=None):
        page = (params or {}).get("page", "1")
        if page == "2":
            raise _http_error(500)
        return page1

    with patch("app.tmdb._cached_get", side_effect=fake_cached_get):
        response = client.get("/search", params={"query": "bat"})

    assert response.status_code == 200
    assert [movie["title"] for movie in response.json()["results"]] == ["Only Page One"]


def test_search_rejects_empty_query(client):
    response = client.get("/search", params={"query": ""})
    assert response.status_code == 422


def test_search_rejects_missing_query(client):
    response = client.get("/search")
    assert response.status_code == 422


def test_search_rejects_whitespace_only_query(client):
    response = client.get("/search", params={"query": "   "})
    assert response.status_code == 422


def test_search_trims_query_before_tmdb_call(client):
    with patch("app.tmdb.search_multi", return_value={"results": []}) as search_multi:
        response = client.get("/search", params={"query": "  bat  "})

    assert response.status_code == 200
    search_multi.assert_called_once_with("bat")


def test_search_all_person_first_page_returns_empty_without_requesting_page2():
    from app import tmdb

    with patch(
        "app.tmdb._cached_get",
        return_value={
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [{"id": 9, "media_type": "person", "name": "Bat Person"}],
        },
    ) as cached_get:
        result = tmdb.search_multi("nothing")

    assert result["results"] == []
    assert result["total_results"] == 0
    assert result["total_pages"] == 1
    cached_get.assert_called_once_with(
        "/search/multi", params={"query": "nothing", "page": "1"}
    )


def test_get_upcoming_movies_uses_us_region(client):
    payload = {
        "results": [{"id": 10, "title": "Soon", "release_date": "2099-01-01"}],
    }

    with patch("app.tmdb._cached_get", return_value=payload) as cached_get:
        response = client.get("/movies/upcoming")

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == payload["results"]
    assert body["total_results"] == 1
    assert body["total_pages"] == 1
    cached_get.assert_called_once_with("/movie/upcoming", params={"region": "US"})


def test_get_upcoming_filters_past_empty_and_null_dates(client):
    # 2026-03-16 02:00 UTC is still 2026-03-15 in America/New_York.
    fixed_utc = datetime(2026, 3, 16, 2, 0, tzinfo=timezone.utc)
    payload = {
        "page": 1,
        "total_pages": 5,
        "total_results": 4,
        "dates": {"maximum": "2026-04-15", "minimum": "2026-03-01"},
        "results": [
            {"id": 1, "title": "Old", "release_date": "2000-01-01"},
            {"id": 2, "title": "Today", "release_date": "2026-03-15"},
            {"id": 3, "title": "Empty", "release_date": ""},
            {"id": 4, "title": "Null", "release_date": None},
            {"id": 5, "title": "Future", "release_date": "2099-06-01"},
        ],
    }

    with (
        patch("app.tmdb.datetime") as mock_datetime,
        patch("app.tmdb._cached_get", return_value=payload),
    ):
        mock_datetime.now.side_effect = lambda tz=None: (
            fixed_utc.astimezone(tz) if tz else fixed_utc.replace(tzinfo=None)
        )
        response = client.get("/movies/upcoming")

    mock_datetime.now.assert_called_with(ZoneInfo("America/New_York"))
    assert response.status_code == 200
    body = response.json()
    assert [movie["title"] for movie in body["results"]] == ["Today", "Future"]
    assert body["total_results"] == 2
    assert body["total_pages"] == 1
    assert body["dates"] == {"maximum": "2026-04-15", "minimum": "2026-03-15"}


@pytest.mark.parametrize("upstream_status", [401, 404, 429, 500, 503])
def test_get_upcoming_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_upcoming_movies", side_effect=_http_error(upstream_status)):
        response = client.get("/movies/upcoming")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_search_rejects_removed_media_specific_routes(client):
    movie_response = client.get("/search/movie", params={"query": "bat"})
    tv_response = client.get("/search/tv", params={"query": "bat"})

    assert movie_response.status_code == 404
    assert tv_response.status_code == 404


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


def test_get_tv_success(client):
    show = {
        "id": 1396,
        "name": "Breaking Bad",
        "overview": "A chemistry teacher turned meth cook.",
        "videos": {"results": []},
        "tagline": None,
    }
    providers = {"results": {"US": {"link": "https://www.themoviedb.org/tv/1396/watch"}}}

    with (
        patch("app.tmdb.get_tv", return_value=show),
        patch("app.tmdb.get_tv_watch_providers", return_value=providers),
    ):
        response = client.get("/tv/1396")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1396
    assert body["name"] == "Breaking Bad"
    assert body["tagline"] == ""
    assert body["streaming_providers"] == providers["results"]["US"]
    assert body["trailer"] is None
    assert body["softcore"] is False


def test_get_tv_unknown_id_returns_404(client):
    with patch("app.tmdb.get_tv", side_effect=_http_error(404)):
        response = client.get("/tv/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "TV show not found"


@pytest.mark.parametrize("upstream_status", [401, 429, 500, 503])
def test_get_tv_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_tv", side_effect=_http_error(upstream_status)):
        response = client.get("/tv/999999999")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_tv_timeout_returns_503(client):
    with patch("app.tmdb.get_tv", side_effect=_timeout_error()):
        response = client.get("/tv/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_tv_request_error_returns_503(client):
    with patch("app.tmdb.get_tv", side_effect=_request_error()):
        response = client.get("/tv/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_tv_season_returns_details_including_specials(client):
    season = {
        "id": 1824,
        "name": "Specials",
        "season_number": 0,
        "episodes": [{"id": 1, "episode_number": 1, "name": "Pilot"}],
    }

    with patch("app.tmdb.get_tv_season", return_value=season) as get_season:
        response = client.get("/tv/1396/season/0")

    assert response.status_code == 200
    assert response.json() == season
    get_season.assert_called_once_with(1396, 0)


def test_get_tv_season_unknown_season_returns_404(client):
    with patch("app.tmdb.get_tv_season", side_effect=_http_error(404)):
        response = client.get("/tv/1396/season/99")

    assert response.status_code == 404
    assert response.json()["detail"] == "TV season not found"


@pytest.mark.parametrize("upstream_status", [401, 429, 500, 503])
def test_get_tv_season_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.get_tv_season", side_effect=_http_error(upstream_status)):
        response = client.get("/tv/1396/season/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_get_tv_season_request_error_returns_503(client):
    with patch("app.tmdb.get_tv_season", side_effect=_request_error()):
        response = client.get("/tv/1396/season/1")

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


@pytest.mark.parametrize("path", ["/tv/0/season/0", "/tv/1396/season/-1"])
def test_get_tv_season_rejects_invalid_ids_and_seasons(client, path):
    response = client.get(path)

    assert response.status_code == 422


def test_get_tv_rejects_non_positive_id(client):
    response = client.get("/tv/0")

    assert response.status_code == 422


@pytest.mark.parametrize("upstream_status", [401, 429, 503])
def test_search_maps_upstream_errors_to_503(client, upstream_status):
    with patch("app.tmdb.search_multi", side_effect=_http_error(upstream_status)):
        response = client.get("/search", params={"query": "bat"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Service unavailable"


def test_search_tmdb_404_returns_503(client):
    with patch("app.tmdb.search_multi", side_effect=_http_error(404)):
        response = client.get("/search", params={"query": "bat"})

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
        session.add(
            Watchlist(
                tmdb_id=88,
                status=WatchlistStatus.WANT,
                added_by="11111111-1111-4111-8111-111111111111",
            )
        )
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


def test_entry_title_is_saved_returned_and_updated(client):
    created = client.post(
        "/entry",
        json={"tmdb_id": 501, "title": "A Saved Movie Title"},
    )

    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert created.json()["title"] == "A Saved Movie Title"

    listed = client.get("/entry")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "A Saved Movie Title"

    updated = client.patch(f"/entry/{entry_id}", json={"title": "Renamed Movie"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed Movie"

    status_update = client.patch(f"/entry/{entry_id}", json={"status": "watched"})
    assert status_update.status_code == 200
    assert status_update.json()["title"] == "Renamed Movie"
    assert client.get("/entry").json()[0]["title"] == "Renamed Movie"


def test_entry_title_is_optional_for_existing_clients(client):
    response = client.post("/entry", json={"tmdb_id": 502})

    assert response.status_code == 201
    assert response.json()["title"] == ""


def test_entry_title_rejects_explicit_null(client):
    response = client.post("/entry", json={"tmdb_id": 503, "title": None})

    assert response.status_code == 422

    created = client.post("/entry", json={"tmdb_id": 504, "title": "Must stay"})
    update = client.patch(f"/entry/{created.json()['id']}", json={"title": None})

    assert update.status_code == 422


def test_legacy_database_title_migration_preserves_rows_and_is_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import inspect, text

    import app.database as database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries ("
                "id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, status VARCHAR NOT NULL, "
                "rating INTEGER, review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(id, tmdb_id, status, review, added_by, created_at, updated_at) "
                "VALUES (1, 88, 'want', '', 'legacy', '2026-01-01', '2026-01-01')"
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_all()
    database.create_all()

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("watchlist_entries")}
    with legacy_engine.connect() as connection:
        row = connection.execute(
            text("SELECT id, tmdb_id, added_by, title FROM watchlist_entries")
        ).one()

    assert "title" in columns
    assert tuple(row) == (1, 88, "legacy-demo", "")
    legacy_engine.dispose()
