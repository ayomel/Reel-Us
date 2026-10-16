"""Run with python -m scripts.qa_tv_search_http while the simulation listens on :4900."""

import os

os.environ["TMDB_API_KEY"] = "test-token"
os.environ["DATABASE_URL"] = "sqlite://"

def main() -> None:
    from fastapi.testclient import TestClient

    from app import tmdb
    from app.main import app

    tmdb.TMDB_BASE_URL = "http://127.0.0.1:4900/tmdb/3"
    tmdb.clear_cache()
    with TestClient(app) as client:
        response = client.get("/search/tv", params={"query": "breaking bad"})
        assert response.status_code == 200, response.text
        result = response.json()["results"][0]
        assert result["id"] == 1396 and result["name"] == "Breaking Bad", result

        for query in (None, "", "   "):
            params = {} if query is None else {"query": query}
            invalid = client.get("/search/tv", params=params)
            assert invalid.status_code == 422, (query, invalid.status_code, invalid.text)

        tmdb.clear_cache()
        failed = client.get("/search/tv", params={"query": "upstream-error"})
        assert failed.status_code == 503, (failed.status_code, failed.text)
        assert failed.json() == {"detail": "Service unavailable"}, failed.text
    print("TV search HTTP smoke passed: success, invalid queries, and upstream 500 -> 503")


if __name__ == "__main__":
    main()
