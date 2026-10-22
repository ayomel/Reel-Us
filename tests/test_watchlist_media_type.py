from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Watchlist


def test_entry_defaults_media_type_to_movie_and_reuses_id_for_tv(client, engine):
    movie = client.post("/entry", json={"tmdb_id": 42, "title": "Movie"})
    tv = client.post("/entry", json={"tmdb_id": 42, "media_type": "tv", "title": "Show"})

    assert movie.status_code == 201
    assert movie.json()["media_type"] == "movie"
    assert tv.status_code == 201
    assert tv.json()["media_type"] == "tv"
    assert tv.json()["id"] != movie.json()["id"]
    assert {entry["media_type"] for entry in client.get("/entry").json()} == {"movie", "tv"}

    with Session(engine) as session:
        assert len(session.exec(select(Watchlist).where(Watchlist.tmdb_id == 42)).all()) == 2


def test_entry_duplicate_same_media_type_keeps_legacy_conflict_message(client):
    assert client.post("/entry", json={"tmdb_id": 42}).status_code == 201
    duplicate = client.post("/entry", json={"tmdb_id": 42, "media_type": "movie"})

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Entry with this tmdb_id already exists"


def test_create_entry_rejects_unknown_media_type(client):
    response = client.post("/entry", json={"tmdb_id": 42, "media_type": "person"})

    assert response.status_code == 422


@pytest.mark.parametrize("media_type", ["movie", "tv"])
def test_concurrent_inserts_enforce_unique_media_type_and_tmdb_pair(tmp_path, media_type):
    import threading

    legacy_engine = create_engine(
        f"sqlite:///{tmp_path / (media_type + '-race.db')}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(legacy_engine)
    barrier = threading.Barrier(2)
    results = []
    lock = threading.Lock()

    def insert_once():
        barrier.wait(timeout=5)
        with Session(legacy_engine) as session:
            session.add(Watchlist(tmdb_id=77, media_type=media_type))
            try:
                session.commit()
                status = 201
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

    assert sorted(results) == [201, 409]
    with Session(legacy_engine) as session:
        rows = session.exec(
            select(Watchlist).where(
                Watchlist.tmdb_id == 77,
                Watchlist.media_type == media_type,
            )
        ).all()
    assert len(rows) == 1
    legacy_engine.dispose()


def test_entry_read_fetches_tmdb_record_matching_media_type(client):
    movie = client.post("/entry", json={"tmdb_id": 51})
    tv = client.post("/entry", json={"tmdb_id": 51, "media_type": "tv"})

    with (
        patch("app.routers.entries.get_movie", return_value={"title": "Movie detail"}) as get_movie,
        patch("app.routers.entries.get_tv", return_value={"name": "Show detail"}) as get_tv,
    ):
        movie_result = client.get(f"/entry/{movie.json()['id']}")
        tv_result = client.get(f"/entry/{tv.json()['id']}")

    assert movie_result.status_code == tv_result.status_code == 200
    assert movie_result.json()["media_type"] == "movie"
    assert movie_result.json()["movie"]["title"] == "Movie detail"
    assert tv_result.json()["media_type"] == "tv"
    assert tv_result.json()["tv"]["name"] == "Show detail"
    get_movie.assert_called_once_with(51)
    get_tv.assert_called_once_with(51)


def test_tv_entry_upstream_404_uses_tv_not_found_message(client):
    from unittest.mock import patch

    created = client.post("/entry", json={"tmdb_id": 52, "media_type": "tv"})
    # The HTTP error helper is exercised with the same exception shape as TMDB.
    import httpx

    request = httpx.Request("GET", "https://api.themoviedb.org/3/tv/52")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    with patch("app.routers.entries.get_tv", side_effect=error):
        result = client.get(f"/entry/{created.json()['id']}")

    assert result.status_code == 404
    assert result.json()["detail"] == "TV show not found"


def test_patch_rejects_identity_changes(client):
    created = client.post("/entry", json={"tmdb_id": 53, "media_type": "tv"})
    entry_id = created.json()["id"]

    assert client.patch(f"/entry/{entry_id}", json={"tmdb_id": 54}).status_code == 422
    assert client.patch(f"/entry/{entry_id}", json={"media_type": "movie"}).status_code == 422
    assert client.patch(f"/entry/{entry_id}", json={"status": "watched"}).status_code == 200


@pytest.mark.parametrize("legacy_kind", ["unique_index", "unique_constraint", "both"])
def test_media_type_migration_preserves_legacy_row_and_is_idempotent(
    tmp_path, monkeypatch, legacy_kind
):
    import app.database as database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / (legacy_kind + '.db')}")
    with legacy_engine.begin() as connection:
        constraint = ", UNIQUE (tmdb_id)" if legacy_kind in {"unique_constraint", "both"} else ""
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "tmdb_id INTEGER NOT NULL, "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, legacy_note VARCHAR NOT NULL DEFAULT 'kept'"
                f"{constraint})"
            )
        )
        if legacy_kind in {"unique_index", "both"}:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX ix_watchlist_entries_tmdb_id "
                    "ON watchlist_entries (tmdb_id)"
                )
            )
        connection.execute(text("CREATE TABLE migration_audit (entry_id INTEGER NOT NULL)"))
        connection.execute(
            text(
                "CREATE TRIGGER watchlist_audit AFTER INSERT ON watchlist_entries "
                "BEGIN INSERT INTO migration_audit (entry_id) VALUES (NEW.id); END"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(id, tmdb_id, title, status, rating, review, added_by, created_at, "
                "updated_at, legacy_note) "
                "VALUES (7, 42, 'Old', 'want', NULL, '', 'legacy', "
                "'2026-01-01', '2026-01-02', 'preserved')"
            )
        )
        connection.execute(
            text("UPDATE sqlite_sequence SET seq = 30 WHERE name = 'watchlist_entries'")
        )
        connection.execute(text("CREATE INDEX legacy_status_idx ON watchlist_entries (status)"))

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_all()
    database.create_all()

    with legacy_engine.begin() as connection:
        columns = {
            column["name"]: column
            for column in inspect(legacy_engine).get_columns("watchlist_entries")
        }
        row = connection.execute(
            text(
                "SELECT id, tmdb_id, title, status, added_by, created_at, updated_at, "
                "media_type, legacy_note "
                "FROM watchlist_entries"
            )
        ).one()
        inserted_id = connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(tmdb_id, title, status, review, added_by, created_at, updated_at, media_type) "
                "VALUES (42, 'TV twin', 'want', '', 'visitor-b', '2026-02-01', '2026-02-02', 'tv') "
                "RETURNING id"
            )
        ).scalar_one()
        media_constraint = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist_entries'")
        ).scalar_one()
        owner_unique = any(
            index.get("unique")
            and index.get("column_names") == ["added_by", "media_type", "tmdb_id"]
            for index in inspect(legacy_engine).get_indexes("watchlist_entries")
        ) or any(
            constraint.get("column_names") == ["added_by", "media_type", "tmdb_id"]
            for constraint in inspect(legacy_engine).get_unique_constraints("watchlist_entries")
        )
        no_single_unique = not any(
            index.get("unique") and index.get("column_names") == ["tmdb_id"]
            for index in inspect(legacy_engine).get_indexes("watchlist_entries")
        ) and not any(
            constraint.get("column_names") == ["tmdb_id"]
            for constraint in inspect(legacy_engine).get_unique_constraints("watchlist_entries")
        )
        audit_count = connection.execute(text("SELECT count(*) FROM migration_audit")).scalar_one()
        preserved_index = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='legacy_status_idx'")
        ).scalar_one()

    assert tuple(row) == (
        7,
        42,
        "Old",
        "want",
        "legacy-demo",
        "2026-01-01",
        "2026-01-02",
        "movie",
        "preserved",
    )
    assert columns["media_type"]["nullable"] is False
    assert "CHECK" in media_constraint.upper()
    assert owner_unique
    assert no_single_unique
    assert inserted_id == 31
    assert audit_count == 2
    assert preserved_index == "CREATE INDEX legacy_status_idx ON watchlist_entries (status)"
    legacy_engine.dispose()


def test_media_type_migration_rejects_duplicate_legacy_ids_without_modifying_data(
    tmp_path, monkeypatch
):
    import app.database as database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'duplicates.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries VALUES "
                "(1, 42, '', 'want', NULL, '', 'a', '2026-01-01', '2026-01-01'), "
                "(2, 42, '', 'want', NULL, '', 'b', '2026-01-02', '2026-01-02')"
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    with pytest.raises(RuntimeError, match="duplicate .*media_type"):
        database.create_all()

    with legacy_engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, added_by FROM watchlist_entries ORDER BY id")
        ).all() == [(1, "a"), (2, "b")]
        assert "media_type" not in {
            column["name"] for column in inspect(legacy_engine).get_columns("watchlist_entries")
        }
    legacy_engine.dispose()


def test_sqlite_rebuild_failure_rolls_back_schema_and_data(tmp_path, monkeypatch):
    import app.database as database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, UNIQUE (tmdb_id))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(id, tmdb_id, status, review, added_by, created_at, updated_at) "
                "VALUES (4, 42, 'want', '', 'keep', '2026-01-01', '2026-01-01')"
            )
        )

    rebuild = database._sqlite_rebuild_for_media_type

    def fail_after_rebuild(conn, indexes, triggers):
        rebuild(conn, indexes, triggers)
        raise RuntimeError("injected failure after table replacement")

    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(database, "_sqlite_rebuild_for_media_type", fail_after_rebuild)
    with pytest.raises(RuntimeError, match="injected failure"):
        database.create_all()

    with legacy_engine.connect() as connection:
        assert "media_type" not in {
            column["name"] for column in inspect(legacy_engine).get_columns("watchlist_entries")
        }
        assert connection.execute(
            text("SELECT id, tmdb_id, added_by FROM watchlist_entries")
        ).one() == (4, 42, "keep")
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type='table' AND name='watchlist_entries_media_new'"
                )
            ).scalar_one()
            == 0
        )
    legacy_engine.dispose()


def test_sqlite_pair_index_name_collision_rolls_back_instead_of_skipping_uniqueness(
    tmp_path, monkeypatch
):
    import app.database as database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'index-collision.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, "
                "media_type VARCHAR NOT NULL DEFAULT 'movie' "
                "CHECK (media_type IN ('movie', 'tv')), "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX uq_watchlist_entries_owner_media_tmdb "
                "ON watchlist_entries (media_type, tmdb_id)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(id, tmdb_id, media_type, status, review, added_by, created_at, updated_at) "
                "VALUES (1, 42, 'movie', 'want', '', 'keep', '2026-01-01', '2026-01-01')"
            )
        )
    monkeypatch.setattr(database, "engine", legacy_engine)

    with pytest.raises(OperationalError):
        database.create_all()

    with legacy_engine.connect() as connection:
        index = next(
            idx
            for idx in inspect(legacy_engine).get_indexes("watchlist_entries")
            if idx["name"] == "uq_watchlist_entries_owner_media_tmdb"
        )
        assert index["unique"] == 0
        assert connection.execute(text("SELECT id, tmdb_id FROM watchlist_entries")).one() == (
            1,
            42,
        )
    legacy_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL must point to a disposable PostgreSQL database",
)
@pytest.mark.parametrize("legacy_kind", ["unique_index", "unique_constraint", "both"])
def test_postgres_media_type_migration_preserves_rows_and_accepts_tv_twin(monkeypatch, legacy_kind):
    import app.database as database

    pg_engine = create_engine(database._normalize_database_url(os.environ["TEST_POSTGRES_URL"]))
    with pg_engine.begin() as connection:
        exists = connection.execute(text("SELECT to_regclass('public.watchlist_entries')")).scalar()
        if exists is not None:
            pytest.fail("TEST_POSTGRES_URL must not already contain public.watchlist_entries")
        unique_constraint = " UNIQUE" if legacy_kind in {"unique_constraint", "both"} else ""
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id SERIAL PRIMARY KEY, tmdb_id INTEGER NOT NULL"
                + unique_constraint
                + ", "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL)"
            )
        )
        if legacy_kind in {"unique_index", "both"}:
            connection.execute(
                text("CREATE UNIQUE INDEX legacy_tmdb_unique ON watchlist_entries (tmdb_id)")
            )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(tmdb_id, status, review, added_by, created_at, updated_at) "
                "VALUES (42, 'want', '', 'legacy', now(), now())"
            )
        )
    monkeypatch.setattr(database, "engine", pg_engine)
    try:
        database.create_all()
        database.create_all()
        with pg_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO watchlist_entries "
                    "(tmdb_id, title, status, review, added_by, created_at, "
                    "updated_at, media_type) "
                    "VALUES (42, 'TV twin', 'want', '', 'visitor-b', now(), now(), 'tv')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO watchlist_entries "
                    "(tmdb_id, title, status, review, added_by, created_at, updated_at) "
                    "VALUES (99, 'Server default', 'want', '', 'legacy', now(), now())"
                )
            )
            rows = connection.execute(
                text("SELECT id, tmdb_id, media_type FROM watchlist_entries ORDER BY id")
            ).all()
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO watchlist_entries "
                        "(tmdb_id, title, status, review, added_by, created_at, updated_at) "
                    "VALUES (42, 'duplicate movie', 'want', '', 'legacy-demo', now(), now())"
                    )
                )
            savepoint.rollback()
            indexes = inspect(connection).get_indexes("watchlist_entries")
            constraints = inspect(connection).get_unique_constraints("watchlist_entries")
        assert [(r.tmdb_id, r.media_type) for r in rows] == [
            (42, "movie"),
            (42, "tv"),
            (99, "movie"),
        ]
        assert not any(
            index.get("unique") and index.get("column_names") == ["tmdb_id"] for index in indexes
        )
        assert any(
            constraint.get("column_names") == ["added_by", "media_type", "tmdb_id"]
            for constraint in constraints
        ) or any(
            index.get("unique")
            and index.get("column_names") == ["added_by", "media_type", "tmdb_id"]
            for index in indexes
        )
    finally:
        with pg_engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS watchlist_entries CASCADE"))
        pg_engine.dispose()


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRES_URL"),
    reason="TEST_POSTGRES_URL must point to a disposable PostgreSQL database",
)
def test_postgres_duplicate_migration_fails_without_schema_or_row_changes(monkeypatch):
    import app.database as database

    pg_engine = create_engine(database._normalize_database_url(os.environ["TEST_POSTGRES_URL"]))
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries (id SERIAL PRIMARY KEY, tmdb_id INTEGER NOT NULL, "
                "title VARCHAR NOT NULL DEFAULT '', status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR NOT NULL, "
                "created_at TIMESTAMPTZ NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(tmdb_id, status, review, added_by, created_at, updated_at) "
                "VALUES (42, 'want', '', 'a', now(), now()), (42, 'want', '', 'b', now(), now())"
            )
        )
    monkeypatch.setattr(database, "engine", pg_engine)
    try:
        with pytest.raises(RuntimeError, match="duplicate .*media_type"):
            database.create_all()
        with pg_engine.connect() as connection:
            assert "media_type" not in {
                column["name"] for column in inspect(connection).get_columns("watchlist_entries")
            }
            rows = connection.execute(
                text("SELECT id, added_by FROM watchlist_entries ORDER BY id")
            ).all()
        assert rows == [(1, "a"), (2, "b")]
    finally:
        with pg_engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS watchlist_entries CASCADE"))
        pg_engine.dispose()
