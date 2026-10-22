from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import MediaType, WatchlistStatus


class WatchlistEntryCreate(BaseModel):
    tmdb_id: int
    media_type: MediaType = MediaType.MOVIE
    title: str = ""
    status: WatchlistStatus = WatchlistStatus.WANT
    rating: int | None = Field(default=None, ge=1, le=10)
    review: str = ""


class WatchlistEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    status: WatchlistStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=10)
    review: str | None = None


class WatchlistEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    media_type: MediaType
    title: str
    status: WatchlistStatus
    rating: int | None
    review: str
    added_by: str
    created_at: datetime
    updated_at: datetime
