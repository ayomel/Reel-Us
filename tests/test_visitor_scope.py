from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

from app.models import Watchlist

VISITOR_A = "11111111-1111-4111-8111-111111111111"
VISITOR_B = "22222222-2222-4222-8222-222222222222"


def test_watchlist_entries_are_scoped_to_the_visitor_header(client):
    created = client.post(
        "/entry",
        json={"tmdb_id": 84, "review": "Private note", "added_by": VISITOR_B},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    assert created.json()["added_by"] == VISITOR_A

    own_entries = client.get("/entry")
    assert [entry["id"] for entry in own_entries.json()] == [entry_id]

    other_headers = {"X-Visitor-ID": VISITOR_B}
    assert client.get("/entry", headers=other_headers).json() == []
    assert client.get(f"/entry/{entry_id}", headers=other_headers).status_code == 404
    assert (
        client.patch(
            f"/entry/{entry_id}",
            headers=other_headers,
            json={"review": "Changed by another visitor"},
        ).status_code
        == 404
    )
    assert client.delete(f"/entry/{entry_id}", headers=other_headers).status_code == 404

    still_owned = client.get("/entry")
    assert still_owned.json()[0]["review"] == "Private note"


def test_different_visitors_can_save_the_same_title(client):
    first = client.post("/entry", json={"tmdb_id": 85})
    second = client.post(
        "/entry",
        headers={"X-Visitor-ID": VISITOR_B},
        json={"tmdb_id": 85},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["added_by"] == VISITOR_A
    assert second.json()["added_by"] == VISITOR_B


def test_visitor_cannot_change_entry_owner(client):
    created = client.post("/entry", json={"tmdb_id": 86})

    update = client.patch(
        f"/entry/{created.json()['id']}",
        json={"added_by": VISITOR_B},
    )

    assert update.status_code == 422


def test_watchlist_requires_a_valid_visitor_id(client):
    original = client.headers.pop("X-Visitor-ID")
    try:
        assert client.get("/entry").status_code == 422
        assert client.post("/entry", json={"tmdb_id": 87}).status_code == 422
    finally:
        client.headers["X-Visitor-ID"] = original

    invalid = client.get("/entry", headers={"X-Visitor-ID": "not-a-uuid"})
    assert invalid.status_code == 422


def test_existing_global_entries_are_archived_during_owner_migration(tmp_path, monkeypatch):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-watchlist.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE watchlist_entries ("
                "id INTEGER PRIMARY KEY, tmdb_id INTEGER NOT NULL, media_type VARCHAR NOT NULL, "
                "title VARCHAR NOT NULL, status VARCHAR NOT NULL, rating INTEGER, "
                "review VARCHAR NOT NULL, added_by VARCHAR, created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "CONSTRAINT uq_watchlist_entries_media_tmdb UNIQUE (media_type, tmdb_id))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO watchlist_entries "
                "(id, tmdb_id, media_type, title, status, rating, review, added_by, "
                "created_at, updated_at) VALUES "
                "(1, 550, 'movie', 'Fight Club', 'WATCHED', 8, 'Legacy review', NULL, "
                "'2026-01-01', '2026-01-02')"
            )
        )

    import app.database as database

    monkeypatch.setattr(database, "engine", legacy_engine)
    database.create_all()
    database.create_all()

    with Session(legacy_engine) as session:
        migrated = session.get(Watchlist, 1)
        assert migrated is not None
        assert migrated.added_by == "legacy-demo"
        assert migrated.review == "Legacy review"

        session.add(
            Watchlist(
                tmdb_id=550,
                media_type="movie",
                title="Fight Club",
                status="want",
                added_by=VISITOR_A,
            )
        )
        session.commit()

    unique_keys = {
        tuple(constraint["column_names"])
        for constraint in inspect(legacy_engine).get_unique_constraints("watchlist_entries")
    }
    assert ("added_by", "media_type", "tmdb_id") in unique_keys
    assert ("media_type", "tmdb_id") not in unique_keys
    columns = {
        column["name"]: column
        for column in inspect(legacy_engine).get_columns("watchlist_entries")
    }
    assert columns["added_by"]["nullable"] is False
    legacy_engine.dispose()
