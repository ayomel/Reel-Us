import pytest

from app.main import cors_origins


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://flickpick.mel-2cb.workers.dev",
        "https://feat-tv-season-browser-flickpick.mel-2cb.workers.dev",
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


@pytest.mark.parametrize(
    "origin",
    [
        "https://flickpick.mel-2cb.workers.dev.evil.com",
        "http://flickpick.mel-2cb.workers.dev",
    ],
)
def test_cors_preflight_rejects_lookalike_and_plain_http_origins(client, origin):
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") is None


def test_cors_origins_parses_env_and_lowercases(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        " https://Preview.Example.com/ , * , http://localhost:5173 ",
    )

    origins = cors_origins()

    assert "https://preview.example.com" in origins
    assert "*" not in origins
    assert origins.count("http://localhost:5173") == 1
    assert "http://127.0.0.1:5173" in origins


def test_cors_origins_defaults_without_env(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert cors_origins() == [
        "http://localhost:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://flickpick.mel-2cb.workers.dev",
        "https://feat-tv-season-browser-flickpick.mel-2cb.workers.dev",
    ]
