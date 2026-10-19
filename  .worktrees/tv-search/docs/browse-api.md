# Browse and search

`GET /search/tv?query=<text>` searches TMDB's TV catalog and returns its response payload unchanged. The query is required, must contain a non-whitespace character, and is trimmed before it is sent upstream. TMDB status and transport failures return `503` with `{"detail":"Service unavailable"}`. Successful TMDB GET responses use the shared 300-second cache, keyed by URL and query parameters.
