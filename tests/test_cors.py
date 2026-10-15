import pytest


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "https://flickpick.mel-2cb.workers.dev",
    ],
)
def test_cors_preflight_allows_default_origins(client, origin):
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_rejects_unknown_origin(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    # Starlette omits ACAO when the request Origin is not allowlisted.
    assert response.headers.get("access-control-allow-origin") is None
