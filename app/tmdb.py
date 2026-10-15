import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
_CACHE_TTL_SECONDS = 300
# Fail TMDB calls after 7s so a hung upstream can't block a worker.
_HTTP_TIMEOUT_SECONDS = 7.0
_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any]] = {}


def _api_key() -> str | None:
    return os.getenv("TMDB_API_KEY")


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}"}


def _cached_get(path: str, params: dict[str, str] | None = None) -> Any:
    url = f"{TMDB_BASE_URL}{path}"
    cache_key = (url, tuple(sorted((params or {}).items())))
    now = time.monotonic()
    cached = _cache.get(cache_key)
    if cached is not None:
        cached_at, payload = cached
        if now - cached_at < _CACHE_TTL_SECONDS:
            return payload

    response = httpx.get(
        url,
        headers=_auth_headers(),
        params=params,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    _cache[cache_key] = (now, payload)
    return payload


def get_trailer_url(videos: list[dict]) -> str | None:
    youtube_trailers = [
        video
        for video in videos
        if video.get("site") == "YouTube" and video.get("type") == "Trailer"
    ]
    if not youtube_trailers:
        return None

    official = [video for video in youtube_trailers if video.get("official") is True]
    chosen = official[0] if official else youtube_trailers[0]
    key = chosen.get("key")
    if not key:
        return None
    return f"https://www.youtube.com/watch?v={key}"


def get_movie(movie_id: int) -> Any:
    return _cached_get(
        f"/movie/{movie_id}",
        params={"append_to_response": "videos"},
    )


def get_movie_watch_providers(movie_id: int) -> Any:
    return _cached_get(f"/movie/{movie_id}/watch/providers")


def get_trending_movies(time_window: str = "week") -> Any:
    return _cached_get(f"/trending/movie/{time_window}")


def get_upcoming_movies() -> Any:
    return _cached_get("/movie/upcoming", params={"region": "US"})


def search_movies(query: str) -> Any:
    # Merge pages 1-2 before sorting so high-popularity hits on page 2
    # (e.g. Batman for "bat") are not dropped by TMDB's default relevance order.
    page1 = _cached_get("/search/movie", params={"query": query, "page": "1"})
    results = list(page1.get("results") or [])
    upstream_total_pages = int(page1.get("total_pages") or 1)
    if upstream_total_pages >= 2:
        try:
            page2 = _cached_get("/search/movie", params={"query": query, "page": "2"})
            results.extend(page2.get("results") or [])
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            # Page 1 alone is still useful; log and continue without page 2.
            logger.warning("TMDB search page 2 failed; using page 1 only: %s", exc)

    seen_ids: set[int] = set()
    unique: list[dict] = []
    for movie in results:
        movie_id = movie.get("id")
        if movie_id in seen_ids:
            continue
        if movie_id is not None:
            seen_ids.add(movie_id)
        unique.append(movie)

    unique.sort(key=lambda movie: movie.get("popularity") or 0, reverse=True)

    # Return one ranked page built from TMDB pages 1-2.
    # total_pages is always 1 because this endpoint does not expose further pages.
    # total_results keeps TMDB's full match count so clients know how large the
    # upstream result set is beyond the merged window we return.
    return {
        **page1,
        "page": 1,
        "total_pages": 1,
        "total_results": int(page1.get("total_results") or len(unique)),
        "results": unique,
    }
