from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


class WatchlistStatus(str, Enum):
    WANT = "want"
    WATCHED = "watched"


class Watchlist(SQLModel, table=True):
    __tablename__ = "watchlist_entries"

    id: int | None = Field(default=None, primary_key=True)

    tmdb_id: int = Field(unique=True, index=True)
    status: WatchlistStatus = Field(default=WatchlistStatus.WANT)

    rating: int | None = Field(default=None, ge=1, le=10)
    review: str = ""
    added_by: str = ""

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
