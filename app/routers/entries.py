from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from httpx import HTTPError
from pydantic import UUID4
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_db
from app.models import MediaType, Watchlist
from app.routers.browse import raise_for_tmdb_failure
from app.schemas import WatchlistEntryCreate, WatchlistEntryRead, WatchlistEntryUpdate
from app.tmdb import get_movie, get_tv

router = APIRouter(tags=["entries"])
VisitorID = Annotated[UUID4, Header(alias="X-Visitor-ID")]


@router.get("/entry", response_model=list[WatchlistEntryRead])
def list_entries(visitor_id: VisitorID, session: Session = Depends(get_db)):
    return session.exec(
        select(Watchlist).where(Watchlist.added_by == str(visitor_id))
    ).all()


@router.post("/entry", response_model=WatchlistEntryRead, status_code=201)
def create_entry(
    body: WatchlistEntryCreate,
    visitor_id: VisitorID,
    session: Session = Depends(get_db),
):
    existing = session.exec(
        select(Watchlist).where(
            Watchlist.tmdb_id == body.tmdb_id,
            Watchlist.media_type == body.media_type,
            Watchlist.added_by == str(visitor_id),
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Entry with this tmdb_id already exists")

    entry = Watchlist.model_validate({**body.model_dump(), "added_by": str(visitor_id)})
    session.add(entry)
    try:
        session.commit()
    except IntegrityError as exc:
        # Covers races where two POSTs pass the pre-check before either commits.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Entry with this tmdb_id already exists",
        ) from exc
    session.refresh(entry)
    return entry


@router.get("/entry/{entry_id}")
def get_entry(
    entry_id: int,
    visitor_id: VisitorID,
    session: Session = Depends(get_db),
):
    entry = session.exec(
        select(Watchlist).where(
            Watchlist.id == entry_id,
            Watchlist.added_by == str(visitor_id),
        )
    ).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        if entry.media_type == MediaType.TV:
            return {**entry.model_dump(), "tv": get_tv(entry.tmdb_id)}
        return {**entry.model_dump(), "movie": get_movie(entry.tmdb_id)}
    except HTTPError as exc:
        raise_for_tmdb_failure(
            exc,
            movie_lookup=entry.media_type == MediaType.MOVIE,
            tv_lookup=entry.media_type == MediaType.TV,
        )


@router.patch("/entry/{entry_id}", response_model=WatchlistEntryRead)
def update_entry(
    entry_id: int,
    body: WatchlistEntryUpdate,
    visitor_id: VisitorID,
    session: Session = Depends(get_db),
):
    entry = session.exec(
        select(Watchlist).where(
            Watchlist.id == entry_id,
            Watchlist.added_by == str(visitor_id),
        )
    ).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(entry, key, value)
    entry.updated_at = datetime.now(UTC)

    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/entry/{entry_id}", status_code=204)
def delete_entry(
    entry_id: int,
    visitor_id: VisitorID,
    session: Session = Depends(get_db),
):
    entry = session.exec(
        select(Watchlist).where(
            Watchlist.id == entry_id,
            Watchlist.added_by == str(visitor_id),
        )
    ).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    session.delete(entry)
    session.commit()
