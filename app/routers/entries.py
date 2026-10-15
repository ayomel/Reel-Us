from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_db
from app.models import Watchlist
from app.routers.browse import raise_for_tmdb_failure
from app.schemas import WatchlistEntryCreate, WatchlistEntryRead, WatchlistEntryUpdate
from app.tmdb import get_movie

router = APIRouter(tags=["entries"])


@router.get("/entry", response_model=list[WatchlistEntryRead])
def list_entries(session: Session = Depends(get_db)):
    return session.exec(select(Watchlist)).all()


@router.post("/entry", response_model=WatchlistEntryRead, status_code=201)
def create_entry(body: WatchlistEntryCreate, session: Session = Depends(get_db)):
    existing = session.exec(select(Watchlist).where(Watchlist.tmdb_id == body.tmdb_id)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Entry with this tmdb_id already exists")

    entry = Watchlist.model_validate(body)
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
def get_entry(entry_id: int, session: Session = Depends(get_db)):
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    try:
        movie = get_movie(entry.tmdb_id)
    except HTTPError as exc:
        raise_for_tmdb_failure(exc, movie_lookup=True)
    return {**entry.model_dump(), "movie": movie}


@router.patch("/entry/{entry_id}", response_model=WatchlistEntryRead)
def update_entry(
    entry_id: int,
    body: WatchlistEntryUpdate,
    session: Session = Depends(get_db),
):
    entry = session.get(Watchlist, entry_id)
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
def delete_entry(entry_id: int, session: Session = Depends(get_db)):
    entry = session.get(Watchlist, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    session.delete(entry)
    session.commit()
