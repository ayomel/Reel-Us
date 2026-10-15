import logging
import os

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

logger = logging.getLogger(__name__)

_UNIQUE_TMDB_INDEX = "ix_watchlist_entries_tmdb_id"


def _normalize_database_url(url: str) -> str:
    if url.startswith("sqlite"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///database.db"))

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, **_engine_kwargs)


def SessionLocal() -> Session:
    return Session(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    import app.models  # noqa: F401  # register table metadata

    SQLModel.metadata.create_all(engine)
    ensure_tmdb_id_unique()


def ensure_tmdb_id_unique() -> None:
    """Add a unique index on watchlist_entries.tmdb_id without deleting rows.

    If duplicate tmdb_ids already exist, log them and skip the constraint so
    the process can still start. Operators must resolve duplicates by hand.
    """
    inspector = inspect(engine)
    if "watchlist_entries" not in inspector.get_table_names():
        return

    indexes = inspector.get_indexes("watchlist_entries")
    unique_constraints = inspector.get_unique_constraints("watchlist_entries")
    has_unique_tmdb = any(
        idx.get("unique") and idx.get("column_names") == ["tmdb_id"] for idx in indexes
    ) or any(constraint.get("column_names") == ["tmdb_id"] for constraint in unique_constraints)
    if has_unique_tmdb:
        return

    with engine.begin() as conn:
        duplicates = conn.execute(
            text(
                "SELECT tmdb_id FROM watchlist_entries "
                "GROUP BY tmdb_id HAVING COUNT(*) > 1 "
                "ORDER BY tmdb_id"
            )
        ).fetchall()
        if duplicates:
            dup_ids = ", ".join(str(row[0]) for row in duplicates)
            logger.error(
                "Skipping unique index on watchlist_entries.tmdb_id because "
                "duplicate tmdb_ids already exist: %s. Resolve the duplicates, "
                "then restart to add the constraint. No rows were deleted.",
                dup_ids,
            )
            return

        # CREATE UNIQUE INDEX works on both SQLite and Postgres and never
        # rebuilds the table, so existing rows are left untouched.
        conn.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_TMDB_INDEX} "
                "ON watchlist_entries (tmdb_id)"
            )
        )
