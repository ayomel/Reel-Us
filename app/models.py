from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, Enum, UniqueConstraint
from sqlmodel import Field, SQLModel


class WatchlistStatus(StrEnum):
    WANT = "want"
    WATCHED = "watched"


class MediaType(StrEnum):
    MOVIE = "movie"
    TV = "tv"


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint(
            "added_by",
            "media_type",
            "tmdb_id",
            name="uq_watchlist_entries_owner_media_tmdb",
        ),
        CheckConstraint("media_type IN ('movie', 'tv')", name="ck_watchlist_entries_media_type"),
    )

    id: int | None = Field(default=None, primary_key=True)

    tmdb_id: int = Field(index=True)
    media_type: MediaType = Field(
        default=MediaType.MOVIE,
        sa_column=Column(
            Enum(
                MediaType,
                native_enum=False,
                values_callable=lambda enum: [item.value for item in enum],
            ),
            nullable=False,
            server_default="movie",
        ),
    )
    title: str = ""
    status: WatchlistStatus = Field(default=WatchlistStatus.WANT)

    rating: int | None = Field(default=None, ge=1, le=10)
    review: str = ""
    added_by: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
