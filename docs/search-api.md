# Search API

`GET /search?query={text}` searches movies and TV shows through TMDB multi-search.
The query is trimmed; empty or whitespace-only values return `422`.
TMDB documents this upstream endpoint at [Search Multi](https://developer.themoviedb.org/reference/search-multi).

The response contains matching movie and TV records from TMDB pages 1 and 2,
sorted by descending popularity. Person results are omitted. Duplicate records
are removed by `(media_type, id)`, so a movie and TV show with the same numeric
ID remain distinct. The response uses `page: 1` and `total_pages: 1`; `total_results`
is the number of returned records. If TMDB page 2 fails, page 1 is returned.
Upstream TMDB failures return `503 Service unavailable`.

Each result includes `media_type` (`movie` or `tv`). Movie records use fields
such as `title`; TV records use `name`.

Results are cached for 300 seconds. The former `/search/movie` and `/search/tv`
routes have been removed.
