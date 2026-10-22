import os

from dotenv import load_dotenv
from sqlalchemy import CheckConstraint, Column, MetaData, Table, UniqueConstraint, inspect, text
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

_UNIQUE_MEDIA_TMDB = "uq_watchlist_entries_owner_media_tmdb"
_MEDIA_TYPE_CHECK = "ck_watchlist_entries_media_type"


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
    ensure_media_type_and_tmdb_unique()
    ensure_watchlist_title()


def ensure_watchlist_title() -> None:
    """Add the optional movie title column to existing watchlists, preserving rows."""
    inspector = inspect(engine)
    if "watchlist_entries" not in inspector.get_table_names():
        return
    if any(column["name"] == "title" for column in inspector.get_columns("watchlist_entries")):
        return

    with engine.begin() as conn:
        # Both SQLite and Postgres support this additive column migration.
        conn.execute(
            text("ALTER TABLE watchlist_entries ADD COLUMN title VARCHAR NOT NULL DEFAULT ''")
        )


def _duplicate_media_keys(conn) -> list[tuple]:
    columns = {column["name"] for column in inspect(conn).get_columns("watchlist_entries")}
    media_expr = "COALESCE(media_type, 'movie')" if "media_type" in columns else "'movie'"
    owner_expr = "COALESCE(added_by, 'legacy-demo')" if "added_by" in columns else "'legacy-demo'"
    return conn.execute(
        text(
            f"SELECT {owner_expr} AS added_by, tmdb_id, {media_expr} AS media_type, COUNT(*) "
            "FROM watchlist_entries "
            f"GROUP BY {owner_expr}, tmdb_id, {media_expr} "
            "HAVING COUNT(*) > 1 ORDER BY added_by, tmdb_id"
        )
    ).fetchall()


def _raise_for_duplicate_media_keys(duplicates: list[tuple]) -> None:
    if duplicates:
        keys = ", ".join(f"({row[0]}, {row[1]}, {row[2]})" for row in duplicates)
        raise RuntimeError(
            "Cannot migrate watchlist_entries: duplicate (added_by, media_type, tmdb_id) keys "
            f"exist: {keys}. Resolve these rows before restarting. No rows were removed."
        )


def _sqlite_rebuild_for_media_type(conn, explicit_indexes: list[str], triggers: list[str]) -> None:
    """Rebuild the table when old SQLite identity constraints need replacing."""
    if "watchlist_entries_media_new" in inspect(conn).get_table_names():
        raise RuntimeError(
            "Cannot migrate watchlist_entries: temporary table "
            "watchlist_entries_media_new already exists. "
            "Inspect it before removing it and restarting. No rows were changed."
        )
    original = Table("watchlist_entries", MetaData(), autoload_with=conn)
    metadata = MetaData()
    columns = [column._copy() for column in original.columns]
    if "media_type" in original.c:
        media_column = next(column for column in columns if column.name == "media_type")
        media_column.nullable = False
        media_column.server_default = text("'movie'")
    if "media_type" not in original.c:
        from sqlalchemy import String

        columns.append(Column("media_type", String, nullable=False, server_default=text("'movie'")))
    if "added_by" not in original.c:
        from sqlalchemy import String

        columns.append(
            Column("added_by", String, nullable=False, server_default=text("'legacy-demo'"))
        )
    else:
        next(column for column in columns if column.name == "added_by").nullable = False
    original_sql = conn.execute(
        text("SELECT sql FROM sqlite_master WHERE type='table' AND name='watchlist_entries'")
    ).scalar_one()
    table_options = (
        {"sqlite_autoincrement": True} if "AUTOINCREMENT" in original_sql.upper() else {}
    )
    rebuilt = Table("watchlist_entries_media_new", metadata, *columns, **table_options)
    for constraint in original.constraints:
        if isinstance(constraint, UniqueConstraint) and set(constraint.columns.keys()) in (
            {"tmdb_id"},
            {"media_type", "tmdb_id"},
            {"added_by", "media_type", "tmdb_id"},
        ):
            continue
        if constraint.__class__.__name__ != "PrimaryKeyConstraint":
            rebuilt.append_constraint(constraint._copy())
    rebuilt.append_constraint(
        CheckConstraint("media_type IN ('movie', 'tv')", name=_MEDIA_TYPE_CHECK)
    )
    rebuilt.append_constraint(
        UniqueConstraint("added_by", "media_type", "tmdb_id", name=_UNIQUE_MEDIA_TMDB)
    )

    metadata.create_all(conn)
    old_names = [column.name for column in original.columns if column.computed is None]
    insert_columns = list(old_names)
    select_columns = list(old_names)
    if "media_type" not in old_names:
        insert_columns.append("media_type")
        select_columns.append("'movie'")
    if "added_by" not in old_names:
        insert_columns.append("added_by")
        select_columns.append("'legacy-demo'")
    quoted_insert = ", ".join(
        conn.dialect.identifier_preparer.quote(name) for name in insert_columns
    )
    quoted_select = ", ".join(
        value if value.startswith("'") else conn.dialect.identifier_preparer.quote(value)
        for value in select_columns
    )
    conn.exec_driver_sql(
        f"INSERT INTO watchlist_entries_media_new ({quoted_insert}) "
        f"SELECT {quoted_select} FROM watchlist_entries"
    )
    conn.exec_driver_sql("DROP TABLE watchlist_entries")
    conn.exec_driver_sql("ALTER TABLE watchlist_entries_media_new RENAME TO watchlist_entries")
    for statement in [*explicit_indexes, *triggers]:
        conn.exec_driver_sql(statement)


def _sqlite_inbound_foreign_keys(conn) -> list[str]:
    tables = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    ).scalars()
    dependents = []
    for table_name in tables:
        quoted = conn.dialect.identifier_preparer.quote(table_name)
        rows = conn.exec_driver_sql(f"PRAGMA foreign_key_list({quoted})").all()
        if any(row[2] == "watchlist_entries" for row in rows):
            dependents.append(table_name)
    return dependents


def ensure_media_type_and_tmdb_unique() -> None:
    """Migrate watchlist identity to (added_by, media_type, tmdb_id)."""
    inspector = inspect(engine)
    if "watchlist_entries" not in inspector.get_table_names():
        return

    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                current = inspect(conn)
                columns = {column["name"] for column in current.get_columns("watchlist_entries")}
                indexes = current.get_indexes("watchlist_entries")
                constraints = current.get_unique_constraints("watchlist_entries")
                identity_keys = {
                    frozenset({"tmdb_id"}),
                    frozenset({"media_type", "tmdb_id"}),
                    frozenset({"added_by", "media_type", "tmdb_id"}),
                }
                has_owner_key = any(
                    frozenset(index.get("column_names") or [])
                    == frozenset({"added_by", "media_type", "tmdb_id"})
                    for index in indexes
                    if index.get("unique")
                ) or any(
                    frozenset(constraint.get("column_names") or [])
                    == frozenset({"added_by", "media_type", "tmdb_id"})
                    for constraint in constraints
                )
                old_table_keys = [
                    constraint
                    for constraint in constraints
                    if frozenset(constraint.get("column_names") or [])
                    in {frozenset({"tmdb_id"}), frozenset({"media_type", "tmdb_id"})}
                ]
                added_by = next(
                    (
                        column
                        for column in current.get_columns("watchlist_entries")
                        if column["name"] == "added_by"
                    ),
                    None,
                )
                media_type = next(
                    (
                        column
                        for column in current.get_columns("watchlist_entries")
                        if column["name"] == "media_type"
                    ),
                    None,
                )
                needs_rebuild = (
                    bool(old_table_keys)
                    or media_type is None
                    or media_type["nullable"]
                    or added_by is None
                    or added_by["nullable"]
                )

                if "added_by" not in columns:
                    conn.exec_driver_sql(
                        "ALTER TABLE watchlist_entries ADD COLUMN added_by VARCHAR NOT NULL "
                        "DEFAULT 'legacy-demo'"
                    )
                    columns.add("added_by")
                elif not has_owner_key:
                    conn.exec_driver_sql(
                        "UPDATE watchlist_entries SET added_by = 'legacy-demo'"
                    )
                else:
                    conn.exec_driver_sql(
                        "UPDATE watchlist_entries SET added_by = 'legacy-demo' "
                        "WHERE added_by IS NULL"
                    )

                if "media_type" in columns:
                    invalid = (
                        conn.execute(
                            text(
                                "SELECT DISTINCT media_type FROM watchlist_entries "
                                "WHERE media_type IS NULL OR media_type NOT IN ('movie', 'tv')"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if invalid:
                        raise RuntimeError(
                            "Cannot migrate watchlist_entries: media_type contains null or "
                            f"unsupported values {invalid}. Resolve them before restarting. "
                            "No rows were removed."
                        )

                _raise_for_duplicate_media_keys(_duplicate_media_keys(conn))

                if needs_rebuild:
                    dependents = _sqlite_inbound_foreign_keys(conn)
                    if dependents:
                        raise RuntimeError(
                            "Cannot rebuild watchlist_entries while other tables reference it: "
                            f"{', '.join(dependents)}. No rows were changed."
                        )
                    table_sql = conn.execute(
                        text(
                            "SELECT sql FROM sqlite_master WHERE type='table' "
                            "AND name='watchlist_entries'"
                        )
                    ).scalar_one()
                    if "AUTOINCREMENT" in table_sql.upper():
                        sequence = conn.execute(
                            text("SELECT seq FROM sqlite_sequence WHERE name='watchlist_entries'")
                        ).scalar_one_or_none()
                    else:
                        sequence = None
                    objects = conn.execute(
                        text(
                            "SELECT name, type, sql FROM sqlite_master "
                            "WHERE tbl_name = 'watchlist_entries' "
                            "AND type IN ('index', 'trigger') AND sql IS NOT NULL "
                            "ORDER BY type, name"
                        )
                    ).all()
                    unique_index_names = {
                        index.get("name")
                        for index in indexes
                        if index.get("unique")
                        and frozenset(index.get("column_names") or []) in identity_keys
                    }
                    explicit_indexes = [
                        sql
                        for name, kind, sql in objects
                        if kind == "index" and name not in unique_index_names
                    ]
                    triggers = [sql for _, kind, sql in objects if kind == "trigger"]
                    _sqlite_rebuild_for_media_type(conn, explicit_indexes, triggers)
                    if sequence is not None:
                        updated = conn.execute(
                            text(
                                "UPDATE sqlite_sequence SET seq = :seq "
                                "WHERE name = 'watchlist_entries'"
                            ),
                            {"seq": sequence},
                        )
                        if updated.rowcount == 0:
                            conn.execute(
                                text(
                                    "INSERT INTO sqlite_sequence (name, seq) "
                                    "VALUES ('watchlist_entries', :seq)"
                                ),
                                {"seq": sequence},
                            )
                else:
                    for index in indexes:
                        if (
                            index.get("unique")
                            and frozenset(index.get("column_names") or [])
                            in {frozenset({"tmdb_id"}), frozenset({"media_type", "tmdb_id"})}
                        ):
                            quoted = conn.dialect.identifier_preparer.quote(index["name"])
                            conn.exec_driver_sql(f"DROP INDEX {quoted}")
                    if not has_owner_key:
                        conn.exec_driver_sql(
                            f"CREATE UNIQUE INDEX {_UNIQUE_MEDIA_TMDB} "
                            "ON watchlist_entries (added_by, media_type, tmdb_id)"
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return

    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            f"Unsupported database dialect for watchlist migration: {engine.dialect.name}"
        )

    with engine.begin() as conn:
        current = inspect(conn)
        columns = {column["name"] for column in current.get_columns("watchlist_entries")}
        if "media_type" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE watchlist_entries ADD COLUMN media_type VARCHAR "
                    "NOT NULL DEFAULT 'movie'"
                )
            )
            columns.add("media_type")
        if "added_by" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE watchlist_entries ADD COLUMN added_by VARCHAR "
                    "NOT NULL DEFAULT 'legacy-demo'"
                )
            )
            columns.add("added_by")
        if "media_type" in columns:
            conn.execute(
                text("UPDATE watchlist_entries SET media_type = 'movie' WHERE media_type IS NULL")
            )
            conn.execute(
                text("ALTER TABLE watchlist_entries ALTER COLUMN media_type SET DEFAULT 'movie'")
            )
            conn.execute(text("ALTER TABLE watchlist_entries ALTER COLUMN media_type SET NOT NULL"))

        current = inspect(conn)
        has_owner_key = any(
            set(constraint.get("column_names") or []) == {"added_by", "media_type", "tmdb_id"}
            for constraint in current.get_unique_constraints("watchlist_entries")
        ) or any(
            index.get("unique")
            and set(index.get("column_names") or []) == {"added_by", "media_type", "tmdb_id"}
            for index in current.get_indexes("watchlist_entries")
        )
        if not has_owner_key:
            conn.execute(text("UPDATE watchlist_entries SET added_by = 'legacy-demo'"))
        conn.execute(
            text("UPDATE watchlist_entries SET added_by = 'legacy-demo' WHERE added_by IS NULL")
        )
        conn.execute(text("ALTER TABLE watchlist_entries ALTER COLUMN added_by SET NOT NULL"))
        _raise_for_duplicate_media_keys(_duplicate_media_keys(conn))

        current = inspect(conn)
        for constraint in current.get_unique_constraints("watchlist_entries"):
            if set(constraint.get("column_names") or []) in (
                {"tmdb_id"},
                {"media_type", "tmdb_id"},
            ):
                name = conn.dialect.identifier_preparer.quote(constraint["name"])
                conn.execute(text(f"ALTER TABLE watchlist_entries DROP CONSTRAINT {name}"))
        current = inspect(conn)
        for index in current.get_indexes("watchlist_entries"):
            if (
                index.get("unique")
                and set(index.get("column_names") or [])
                in ({"tmdb_id"}, {"media_type", "tmdb_id"})
            ):
                name = conn.dialect.identifier_preparer.quote(index["name"])
                conn.execute(text(f"DROP INDEX {name}"))
        checks = current.get_check_constraints("watchlist_entries")
        if not any(check.get("name") == _MEDIA_TYPE_CHECK for check in checks):
            conn.execute(
                text(
                    f"ALTER TABLE watchlist_entries ADD CONSTRAINT {_MEDIA_TYPE_CHECK} "
                    "CHECK (media_type IN ('movie', 'tv'))"
                )
            )
        current = inspect(conn)
        has_owner_key = any(
            set(constraint.get("column_names") or []) == {"added_by", "media_type", "tmdb_id"}
            for constraint in current.get_unique_constraints("watchlist_entries")
        ) or any(
            index.get("unique")
            and set(index.get("column_names") or []) == {"added_by", "media_type", "tmdb_id"}
            for index in current.get_indexes("watchlist_entries")
        )
        if not has_owner_key:
            conn.execute(
                text(
                    f"ALTER TABLE watchlist_entries ADD CONSTRAINT {_UNIQUE_MEDIA_TMDB} "
                    "UNIQUE (added_by, media_type, tmdb_id)"
                )
            )
