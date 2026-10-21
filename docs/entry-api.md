# Watchlist entries

Watchlist entries can refer to movies or TV shows. `media_type` accepts `movie` or `tv` and defaults to `movie` for existing clients. TMDB IDs are unique within a media type, so the same numeric ID can appear once as a movie and once as a TV show.

TV entries represent whole shows; the watchlist does not track individual episodes. Save the movie search result's `title` or the TV search result's `name` in the watchlist `title` field. That saved label remains optional and defaults to an empty string when omitted.

## Create an entry

`POST /entry` accepts the existing watchlist fields and an optional `media_type`:

```json
{
  "tmdb_id": 1396,
  "media_type": "tv",
  "title": "Breaking Bad",
  "status": "want"
}
```

The response includes `media_type`. A repeated `(media_type, tmdb_id)` pair returns `409` with the existing detail `Entry with this tmdb_id already exists`. A matching ID with the other media type is allowed.

## List and read entries

`GET /entry` returns a mixed list. Every item includes `media_type`; entries created before this field was introduced are migrated as `movie`.

`GET /entry/{entry_id}` fetches the matching TMDB record and includes it under `movie` or `tv`, according to the saved media type. A movie lookup that returns 404 responds with `Movie not found`; a TV lookup responds with `TV show not found`. Other TMDB HTTP and connection failures respond with `503 Service unavailable`.

## Update an entry

`PATCH /entry/{entry_id}` updates `title`, `status`, `rating`, `review`, and `added_by`. The entry identity is fixed after creation; including `tmdb_id` or `media_type` is rejected with `422`. Omitted fields stay unchanged, and `title` cannot be `null`.

## Database rollout and rollback

Before deploying, pause watchlist writes and take a verified database backup. The startup migration adds a non-null `media_type` defaulting to `movie`, validates existing IDs, and changes uniqueness from `tmdb_id` to `(media_type, tmdb_id)` while preserving existing rows and IDs. It fails with an actionable error if duplicate legacy identities need attention; resolve those rows and retry while writes remain paused.

After the new application starts, verify that existing entries appear as movies, a TV entry can share a numeric ID with a movie, and repeating the same type and ID returns `409`. Resume writes after those checks pass.

To roll back, pause writes, restore the verified pre-deployment backup, then deploy the previous application version. Restoring the backup is required because the older schema cannot represent both media types for the same TMDB ID.
