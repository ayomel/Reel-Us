from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


class WatchlistStatus(StrEnum):
    WANT = "want"
    WATCHED = "watched"


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlist_entries"

    id: int | None = Field(default=None, primary_key=True)

    tmdb_id: int = Field(unique=True, index=True)
    title: str = ""
    status: WatchlistStatus = Field(default=WatchlistStatus.WANT)

    rating: int | None = Field(default=None, ge=1, le=10)
    review: str = ""
    added_by: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
