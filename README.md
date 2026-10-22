# FlickPick API

FlickPick's FastAPI service for movie and TV discovery, backed by TMDB, with an anonymous per-browser watchlist stored in SQLite or PostgreSQL.

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

Interactive API documentation is available at `/docs` (Swagger UI), `/redoc`, and `/openapi.json`. FastAPI also serves `/docs/oauth2-redirect` for the Swagger UI. There are no accounts or authentication. Every `/entry` request must include an `X-Visitor-ID` header containing a UUID v4. The frontend creates and stores this anonymous ID in browser local storage. The API uses it to scope entries; anyone with the same ID can access that browser's list, so this is not account security. Clearing browser data loses access to that list.

Before visitor scoping, watchlist rows were shared across clients. The startup migration keeps those rows and assigns them the reserved owner `legacy-demo`; UUID v4 visitors cannot retrieve or modify them. They remain archived in the database for demo/history purposes.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/` | Returns `{"message":"Hello World"}`. |
| GET | `/health` | Returns `{"status":"ok"}` as a liveness check. It does not check database or TMDB availability. |
| GET | `/movies/upcoming` | Returns TMDB's US upcoming movies filtered to releases today or later in the `America/New_York` timezone. |
| GET | `/movies/{movie_id}` | Returns TMDB movie details, US streaming providers, and a YouTube trailer URL when available. |
| GET | `/movies/{movie_id}/recommendations` | Returns TMDB movie recommendations with `media_type: "movie"` on each result. |
| GET | `/tv/{tv_id}` | Returns TMDB TV details, US streaming providers, a YouTube trailer URL when available, and the placeholder `softcore: false` field, which is not a content classification. Null `tagline`, `homepage`, `first_air_date`, and `last_air_date` values are returned as empty strings. |
| GET | `/tv/{tv_id}/recommendations` | Returns TMDB TV recommendations with `media_type: "tv"` on each result. |
| GET | `/trending/movies` | Returns TMDB movies trending for the week. |
| GET | `/search?query={text}` | Searches movies and TV shows. Details are below. |
| GET | `/entry` | Lists entries owned by the `X-Visitor-ID` UUID v4. |
| POST | `/entry` | Creates an entry for the `X-Visitor-ID` and returns `201 Created`. |
| GET | `/entry/{entry_id}` | Returns an owned entry with its current TMDB record under `movie` or `tv`; another visitor's entry returns `404`. |
| PATCH | `/entry/{entry_id}` | Updates editable fields on an owned entry; another visitor's entry returns `404`. |
| DELETE | `/entry/{entry_id}` | Deletes an owned entry and returns `204 No Content`; another visitor's entry returns `404`. |

### Search behavior

`query` must contain a non-whitespace character; it is trimmed before sending to TMDB. The API combines the first two TMDB multi-search pages, filters out people, removes duplicate `(media_type, id)` results, and sorts by descending popularity. The response describes one page (`page: 1`, `total_pages: 1`), and `total_results` counts returned movie and TV records. There is no page parameter. If TMDB's second page fails, the API returns results from its first page.

### Watchlist fields

Create requests require `tmdb_id`. `media_type` accepts `movie` or `tv` and defaults to `movie`; `title` defaults to an empty string, `status` defaults to `want`, and `rating` and `review` default to null and an empty string respectively. The server sets `added_by` from the `X-Visitor-ID` header; clients cannot choose or change an entry's owner. Save the movie's `title` or TV show's `name` in `title` if you want a display label. The API stores a whole TV show, not individual episodes.

`status` accepts `want` or `watched`. `rating` is an integer from 1 to 10 or null. The same TMDB ID may be saved once as a movie and once as a TV show; a duplicate `(media_type, tmdb_id)` for the same visitor returns `409 Conflict`.

PATCH can change `title`, `status`, `rating`, and `review`. Omitted fields stay unchanged. Entry identity and ownership cannot be changed; including `tmdb_id`, `media_type`, or `added_by` returns `422`. A missing or other visitor's entry returns `404` for read, update, and delete operations.

Example `POST /entry` request (include the same UUID v4 header on all `/entry` requests):

```http
X-Visitor-ID: 4fbd4c74-6a67-4c6f-9a11-01964d299977
```

Request body:

```json
{"tmdb_id": 1396, "media_type": "tv", "title": "Breaking Bad", "status": "want"}
```

Example `PATCH /entry/1` body:

```json
{"status": "watched", "rating": 9, "review": "Worth watching."}
```

Create, list, and update responses include the saved entry fields: `id`, `tmdb_id`, `media_type`, `title`, `status`, `rating`, `review`, `added_by`, `created_at`, and `updated_at`. `added_by` is the server-assigned visitor ID. The path `entry_id` is the local entry ID, not its TMDB ID.

### Errors and upstream data

Invalid input returns `422`; movie and TV IDs on detail and recommendation routes must be positive integers. Missing movie or TV records return `404` on their detail or recommendation routes, and other TMDB failures return `503 Service unavailable`. Watchlist detail lookups return `404 Entry not found` when the local entry is missing; a missing TMDB record also returns `404`.

`GET /movies/{movie_id}` and `GET /tv/{tv_id}` include raw `videos` data and add a `trailer` URL for the first official YouTube trailer, falling back to the first YouTube trailer or null. Streaming providers contain the US provider data from TMDB, or an empty object if no US data is available. `GET /entry/{entry_id}` returns raw TMDB details with videos under `movie` or `tv`; it does not add the convenience `trailer` or `streaming_providers` fields.

TMDB responses are cached in memory for 300 seconds. Upstream HTTP calls have a seven-second timeout.
