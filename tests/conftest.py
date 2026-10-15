import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

# Use an isolated SQLite DB before the app imports its engine.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("TMDB_API_KEY", "test-key")

from app.database import get_db
from app.main import create_app
from app import tmdb


@pytest.fixture()
def client():
    tmdb.clear_cache()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    tmdb.clear_cache()
