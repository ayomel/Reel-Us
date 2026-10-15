import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Point the app at an in-memory DB before app.database is imported by create_app.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("TMDB_API_KEY", "test-token")

from app import tmdb
from app.database import get_db
from app.main import create_app


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture()
def client(engine):
    tmdb.clear_cache()
    app = create_app()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    tmdb.clear_cache()
