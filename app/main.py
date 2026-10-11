from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_all
from app.routers import browse, entries

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "https://flickpick.mel-2cb.workers.dev",
        ],
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
