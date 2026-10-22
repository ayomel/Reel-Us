from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query
from httpx import HTTPStatusError, RequestError

from app import tmdb

router = APIRouter(tags=["browse"])

_TV_STRING_DEFAULTS = ("tagline", "homepage", "first_air_date", "last_air_date")


def _with_tv_string_defaults(show: dict[str, Any]) -> dict[str, Any]:
    for key in _TV_STRING_DEFAULTS:
        if show.get(key) is None:
            show[key] = ""
    return show


def raise_for_tmdb_failure(
    exc: Exception,
    *,
    movie_lookup: bool = False,
    tv_lookup: bool = False,
    tv_season_lookup: bool = False,
) -> None:
    """Map TMDB failures to API errors.

    A TMDB 404 is 404 on movie, TV, or TV season detail lookups. Search,
    upcoming, trending, and every other TMDB failure become 503 Service unavailable.
    """
    if isinstance(exc, HTTPStatusError) and exc.response.status_code == 404:
        if movie_lookup:
            raise HTTPException(status_code=404, detail="Movie not found") from exc
        if tv_lookup:
            raise HTTPException(status_code=404, detail="TV show not found") from exc
        if tv_season_lookup:
            raise HTTPException(status_code=404, detail="TV season not found") from exc
    raise HTTPException(status_code=503, detail="Service unavailable") from exc


@router.get("/movies/upcoming")
def get_upcoming_movies():
    try:
        return tmdb.get_upcoming_movies()
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)


@router.get("/movies/discover")
def discover_movies(
    genre_ids: Annotated[
        str,
        Query(
            alias="with_genres",
            pattern=r"^[1-9]\d*(?:\|[1-9]\d*)*$",
        ),
    ],
):
    try:
        payload = tmdb.discover_movies(genre_ids)
        return {
            **payload,
            "results": [
                {**result, "media_type": "movie"}
                for result in (payload.get("results") or [])
            ],
        }
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)


@router.get("/movies/{movie_id}")
def get_movie(movie_id: int):
    try:
        movie = tmdb.get_movie(movie_id)
        providers = tmdb.get_movie_watch_providers(movie_id)
        us_providers = providers.get("results", {}).get("US", {})
        videos = movie.get("videos", {}).get("results", [])
        trailer = tmdb.get_trailer_url(videos)
        return {**movie, "streaming_providers": us_providers, "trailer": trailer}
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc, movie_lookup=True)


@router.get("/movies/{movie_id}/recommendations")
def get_movie_recommendations(movie_id: Annotated[int, Path(gt=0)]):
    try:
        payload = tmdb.get_movie_recommendations(movie_id)
        return {
            **payload,
            "results": [
                {**result, "media_type": "movie"}
                for result in (payload.get("results") or [])
            ],
        }
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc, movie_lookup=True)


@router.get("/tv/discover")
def discover_tv(
    genre_ids: Annotated[
        str,
        Query(
            alias="with_genres",
            pattern=r"^[1-9]\d*(?:\|[1-9]\d*)*$",
        ),
    ],
):
    try:
        payload = tmdb.discover_tv(genre_ids)
        return {
            **payload,
            "results": [
                {**result, "media_type": "tv"}
                for result in (payload.get("results") or [])
            ],
        }
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)


@router.get("/tv/{tv_id}")
def get_tv(tv_id: Annotated[int, Path(gt=0)]):
    try:
        show = tmdb.get_tv(tv_id)
        providers = tmdb.get_tv_watch_providers(tv_id)
        us_providers = providers.get("results", {}).get("US", {})
        videos = show.get("videos", {}).get("results", [])
        trailer = tmdb.get_trailer_url(videos)
        payload = {
            **show,
            "streaming_providers": us_providers,
            "trailer": trailer,
            "softcore": False,
        }
        return _with_tv_string_defaults(payload)
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc, tv_lookup=True)


@router.get("/tv/{tv_id}/recommendations")
def get_tv_recommendations(tv_id: Annotated[int, Path(gt=0)]):
    try:
        payload = tmdb.get_tv_recommendations(tv_id)
        return {
            **payload,
            "results": [
                {**result, "media_type": "tv"}
                for result in (payload.get("results") or [])
            ],
        }
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc, tv_lookup=True)


@router.get("/tv/{tv_id}/season/{season_number}")
def get_tv_season(
    tv_id: Annotated[int, Path(gt=0)],
    season_number: Annotated[int, Path(ge=0)],
):
    try:
        return tmdb.get_tv_season(tv_id, season_number)
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc, tv_season_lookup=True)


@router.get("/trending/movies")
def get_trending_movies():
    try:
        return tmdb.get_trending_movies()
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)


@router.get("/search")
def search(query: str = Query(min_length=1, pattern=r".*\S.*")):
    try:
        return tmdb.search_multi(query.strip())
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)
