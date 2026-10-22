from app.main import app


def test_openapi_title_uses_product_name():
    assert app.openapi()["info"]["title"] == "FlickPick API"
