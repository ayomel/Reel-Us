import logging
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

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


def clear_cache() -> None:
    _cache.clear()


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


def get_tv(tv_id: int) -> Any:
    return _cached_get(
        f"/tv/{tv_id}",
        params={"append_to_response": "videos"},
    )


def get_tv_watch_providers(tv_id: int) -> Any:
    return _cached_get(f"/tv/{tv_id}/watch/providers")


def get_trending_movies(time_window: str = "week") -> Any:
    return _cached_get(f"/trending/movie/{time_window}")


def get_upcoming_movies() -> Any:
    payload = _cached_get("/movie/upcoming", params={"region": "US"})
    # TMDB's upcoming list can include already-released titles.
    # Keep titles released today or later.
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    results = [
        movie
        for movie in (payload.get("results") or [])
        if (movie.get("release_date") or "") >= today
    ]
    out = {
        **payload,
        "results": results,
        "total_results": len(results),
        "total_pages": 1,
    }
    dates = payload.get("dates")
    if isinstance(dates, dict):
        out["dates"] = {**dates, "minimum": today}
    return out


def search_multi(query: str) -> Any:
    # Merge pages 1-2 before sorting so high-popularity hits on page 2
    # are not dropped by TMDB's default relevance order.
    page1 = _cached_get("/search/multi", params={"query": query, "page": "1"})
    results = list(page1.get("results") or [])
    upstream_total_pages = int(page1.get("total_pages") or 1)
    if upstream_total_pages >= 2:
        try:
            page2 = _cached_get("/search/multi", params={"query": query, "page": "2"})
            results.extend(page2.get("results") or [])
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            # Page 1 alone is still useful; log and continue without page 2.
            logger.warning("TMDB search page 2 failed; using page 1 only: %s", exc)

    seen: set[tuple[str, int]] = set()
    unique: list[dict] = []
    for item in results:
        media_type = item.get("media_type")
        item_id = item.get("id")
        if media_type not in {"movie", "tv"} or item_id is None:
            continue
        key = (media_type, item_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    unique.sort(key=lambda item: item.get("popularity") or 0, reverse=True)

    # One ranked page is built from TMDB pages 1-2; totals describe returned
    # movie and TV records only, excluding people and duplicate hits.
    return {
        **page1,
        "page": 1,
        "total_pages": 1,
        "total_results": len(unique),
        "results": unique,
    }
