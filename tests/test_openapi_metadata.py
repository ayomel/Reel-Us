from app.main import app


def test_openapi_title_uses_product_name():
    assert app.openapi()["info"]["title"] == "FlickPick API"


def test_openapi_documents_required_genre_discovery_filters():
    paths = app.openapi()["paths"]

    for path in ("/movies/discover", "/tv/discover"):
        parameters = paths[path]["get"]["parameters"]
        genre_filter = next(
            parameter
            for parameter in parameters
            if parameter["name"] == "with_genres"
        )
        assert genre_filter["in"] == "query"
        assert genre_filter["required"] is True
        assert genre_filter["schema"]["pattern"] == r"^[1-9]\d*(?:\|[1-9]\d*)*$"
