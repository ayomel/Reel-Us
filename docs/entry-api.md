# Watchlist entry title

`POST /entry` accepts an optional `title` string and stores it with the TMDB ID. If omitted, it is saved as an empty string for existing clients. `GET /entry` and the create, update, and read responses include the saved title. `PATCH /entry/{entry_id}` may include `title` to change it; omitting it leaves the current title unchanged. A title cannot be `null`.
