import os

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

load_dotenv()

def _normalize_database_url(url: str) -> str:
    if url.startswith("sqlite"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite:///database.db")
)

_engine_kwargs: dict = {}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, **_engine_kwargs)


def SessionLocal() -> Session:
    return Session(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    import app.models

    SQLModel.metadata.create_all(engine)
