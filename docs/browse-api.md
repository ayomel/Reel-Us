# Browse and search

`GET /search/tv?query=<text>` searches TMDB's TV catalog and returns its response payload unchanged. The query is required, must contain a non-whitespace character, and is trimmed before it is sent upstream. TMDB status and transport failures return `503` with `{"detail":"Service unavailable"}`. Successful TMDB GET responses use the shared 300-second cache, keyed by URL and query parameters.

To check the route over real HTTP against a local TMDB simulation, run these commands from the repository root in separate terminals:

```sh
postman simulation run postman/simulations/tv-search.sim.yaml --port 4900 --no-history
python -m scripts.qa_tv_search_http
```

The smoke check covers a TV result, invalid queries, and an upstream failure. Stop the simulation with Ctrl+C afterward. The mock models TMDB's [TV search contract](https://developer.themoviedb.org/reference/search-tv); this check does not contact live TMDB.
