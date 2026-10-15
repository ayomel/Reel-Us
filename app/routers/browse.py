from fastapi import APIRouter, HTTPException
from httpx import HTTPStatusError

from app import tmdb

router = APIRouter(tags=["browse"])


@router.get("/movies/{movie_id}")
def get_movie(movie_id: int):
    try:
        movie = tmdb.get_movie(movie_id)
        providers = tmdb.get_movie_watch_providers(movie_id)
        us_providers = providers.get("results", {}).get("US", {})
        videos = movie.get("videos", {}).get("results", [])
        trailer = tmdb.get_trailer_url(videos)
        return {**movie, "streaming_providers": us_providers, "trailer": trailer}
    except HTTPStatusError as exc:
        # Unknown/unavailable movie ids must stay a clean 404. Passing through
        # TMDB 401/500 confuses clients that treat those as auth or server faults.
        if exc.response.status_code in {401, 404, 500}:
            raise HTTPException(status_code=404, detail="Movie not found") from exc
        raise HTTPException(status_code=exc.response.status_code, detail="TMDB request failed") from exc


@router.get("/trending/movies")
def get_trending_movies():
    try:
        return tmdb.get_trending_movies()
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="TMDB request failed") from exc


@router.get("/search/movie")
def search_movies(query: str):
    try:
        return tmdb.search_movies(query)
    except HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="TMDB request failed") from exc
