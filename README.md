# Movies API

A FastAPI service for movie and TV discovery, backed by TMDB, with a shared watchlist stored in SQLite or PostgreSQL.

## Run locally

```powershell
uv sync
Copy-Item .env.example .env
```

Set `TMDB_API_KEY` in `.env` to a TMDB read access token. `DATABASE_URL` defaults to `sqlite:///database.db`; set it to a PostgreSQL URL to use PostgreSQL. Then start the development server:

```powershell
uv run fastapi dev app/main.py
```

The server runs at `http://127.0.0.1:8000` by default. The app creates its database tables at startup. It allows the two localhost Vite origins and the configured frontend origin. Add other comma-separated origins with `CORS_ORIGINS`.

## Endpoints

Interactive API documentation is available at `/docs` (Swagger UI), `/redoc`, and `/openapi.json`. FastAPI also serves `/docs/oauth2-redirect` for the Swagger UI. There is no authentication; watchlist entries are shared by all clients using the same database.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/` | Returns `{"message":"Hello World"}`. |
| GET | `/health` | Returns `{"status":"ok"}` as a liveness check. It does not check database or TMDB availability. |
| GET | `/movies/upcoming` | Returns TMDB's US upcoming movies filtered to releases today or later in the `America/New_York` timezone. |
| GET | `/movies/{movie_id}` | Returns TMDB movie details, US streaming providers, and a YouTube trailer URL when available. |
| GET | `/tv/{tv_id}` | Returns TMDB TV details, US streaming providers, a YouTube trailer URL when available, and the placeholder `softcore: false` field, which is not a content classification. Null `tagline`, `homepage`, `first_air_date`, and `last_air_date` values are returned as empty strings. |
| GET | `/trending/movies` | Returns TMDB movies trending for the week. |
| GET | `/search?query={text}` | Searches movies and TV shows. Details are below. |
| GET | `/entry` | Lists watchlist entries. |
| POST | `/entry` | Creates a watchlist entry and returns `201 Created`. |
| GET | `/entry/{entry_id}` | Returns an entry with its current TMDB record under `movie` or `tv`. |
| PATCH | `/entry/{entry_id}` | Updates editable watchlist fields. |
| DELETE | `/entry/{entry_id}` | Deletes an entry and returns `204 No Content`. |

### Search behavior

`query` must contain a non-whitespace character; it is trimmed before sending to TMDB. The API combines the first two TMDB multi-search pages, filters out people, removes duplicate `(media_type, id)` results, and sorts by descending popularity. The response describes one page (`page: 1`, `total_pages: 1`), and `total_results` counts returned movie and TV records. There is no page parameter. If TMDB's second page fails, the API returns results from its first page.

### Watchlist fields

Create requests require `tmdb_id`. `media_type` accepts `movie` or `tv` and defaults to `movie`; `title` defaults to an empty string, `status` defaults to `want`, `rating` and `review` default to null and an empty string respectively, and `added_by` defaults to an empty string. Save the movie's `title` or TV show's `name` in `title` if you want a display label. The API stores a whole TV show, not individual episodes.

`status` accepts `want` or `watched`. `rating` is an integer from 1 to 10 or null. The same TMDB ID may be saved once as a movie and once as a TV show; a duplicate `(media_type, tmdb_id)` returns `409 Conflict`.

PATCH can change `title`, `status`, `rating`, `review`, and `added_by`. Omitted fields stay unchanged. The entry identity cannot be changed; including `tmdb_id` or `media_type` returns `422`. A missing entry returns `404` for read, update, and delete operations.

Example `POST /entry` body:

```json
{"tmdb_id": 1396, "media_type": "tv", "title": "Breaking Bad", "status": "want"}
```

Example `PATCH /entry/1` body:

```json
{"status": "watched", "rating": 9, "review": "Worth watching."}
```

Create, list, and update responses include the saved entry fields: `id`, `tmdb_id`, `media_type`, `title`, `status`, `rating`, `review`, `added_by`, `created_at`, and `updated_at`. The path `entry_id` is the local entry ID, not its TMDB ID.

### Errors and upstream data

Invalid input returns `422`; `tv_id` must be a positive integer. Missing movie or TV records return `404` on their detail routes, and other TMDB failures return `503 Service unavailable`. Watchlist detail lookups return `404 Entry not found` when the local entry is missing; a missing TMDB record also returns `404`.

`GET /movies/{movie_id}` and `GET /tv/{tv_id}` include raw `videos` data and add a `trailer` URL for the first official YouTube trailer, falling back to the first YouTube trailer or null. Streaming providers contain the US provider data from TMDB, or an empty object if no US data is available. `GET /entry/{entry_id}` returns raw TMDB details with videos under `movie` or `tv`; it does not add the convenience `trailer` or `streaming_providers` fields.

TMDB responses are cached in memory for 300 seconds. Upstream HTTP calls have a seven-second timeout.
