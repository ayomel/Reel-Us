import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_all
from app.routers import browse, entries

load_dotenv()

# Defaults cover local Vite, the live Workers frontend, and its PR preview.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:5174",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://flickpick.mel-2cb.workers.dev",
    "https://feat-tv-season-browser-flickpick.mel-2cb.workers.dev",
)


def cors_origins() -> list[str]:
    """Return allowlisted CORS origins. Never includes a wildcard."""
    origins = list(_DEFAULT_CORS_ORIGINS)
    extra = os.getenv("CORS_ORIGINS", "")
    for origin in extra.split(","):
        origin = origin.strip().rstrip("/").lower()
        if not origin or origin == "*" or origin in origins:
            continue
        origins.append(origin)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(browse.router)
    app.include_router(entries.router)

    @app.get("/")
    def home():
        return {"message": "Hello World"}

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    return app


app = create_app()
