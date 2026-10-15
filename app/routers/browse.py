from fastapi import APIRouter, HTTPException, Query
from httpx import HTTPStatusError, RequestError

from app import tmdb

router = APIRouter(tags=["browse"])


def raise_for_tmdb_failure(exc: Exception, *, movie_lookup: bool = False) -> None:
    """Map TMDB failures to API errors.

    Only TMDB's 404 means the movie doesn't exist. Auth, rate limits, 5xx,
    timeouts, and connection errors all become 503 Service unavailable.
    """
    if movie_lookup and isinstance(exc, HTTPStatusError) and exc.response.status_code == 404:
        raise HTTPException(status_code=404, detail="Movie not found") from exc
    raise HTTPException(status_code=503, detail="Service unavailable") from exc


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


@router.get("/trending/movies")
def get_trending_movies():
    try:
        return tmdb.get_trending_movies()
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)


@router.get("/search/movie")
def search_movies(query: str = Query(min_length=1)):
    try:
        return tmdb.search_movies(query)
    except (HTTPStatusError, RequestError) as exc:
        raise_for_tmdb_failure(exc)
