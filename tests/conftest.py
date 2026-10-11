"""Shared test fixtures.

Every test gets:
  * its own temporary SQLite database file,
  * its own temporary certificate folder,
so tests never touch the real database or any previously generated certificates.

How background tasks are tested
-------------------------------
FastAPI's TestClient waits until the whole request, INCLUDING its background tasks, has
finished before it returns the response. So after `client.post(...)` returns, the
certificates have already been generated and `client.get(...)` sees the final result.
No sleeping or polling is needed, which keeps the tests fast and deterministic.

We deliberately do NOT use `with TestClient(app):` because that would run the
application's startup code, which creates the real database file.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import config, database
from app.database import Base, make_engine
from app.main import app


@pytest.fixture()
def cert_dir(tmp_path, monkeypatch):
    """A temporary folder that replaces the real certificate output folder."""
    folder = tmp_path / "certificates"
    folder.mkdir()
    monkeypatch.setattr(config, "CERTIFICATE_DIR", folder)
    return folder


@pytest.fixture()
def db_session_factory(tmp_path, monkeypatch):
    """A temporary SQLite database. Replaces database.SessionLocal for the whole app."""
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    # Both the request dependency (get_db) and the background processor read
    # database.SessionLocal when they run, so this one line redirects everything.
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(db_session_factory, cert_dir):
    return TestClient(app)


@pytest.fixture()
def valid_recipients():
    return [
        {"name": "Asha Verma", "email": "asha@example.com"},
        {"name": "Rohan Mehta", "email": "rohan@example.com"},
        {"name": "Priya Nair", "email": "priya@example.com", "course_name": "Python for Data Science"},
    ]


@pytest.fixture()
def make_payload():
    """Build a request body; keyword arguments override the defaults."""

    def _make(recipients, **overrides):
        payload = {
            "event_name": "Advanced Python Bootcamp",
            "issue_date": "2026-10-11",
            "recipients": recipients,
        }
        payload.update(overrides)
        return payload

    return _make


@pytest.fixture()
def create_job(client, make_payload):
    """POST a job, check it was accepted, return the JSON body."""

    def _create(recipients, **overrides):
        response = client.post("/api/v1/jobs", json=make_payload(recipients, **overrides))
        assert response.status_code == 202, response.text
        return response.json()

    return _create


@pytest.fixture()
def get_job(client):
    """GET a job's status, check it exists, return the JSON body."""

    def _get(job_id):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        return response.json()

    return _get


@pytest.fixture()
def defer_processing(monkeypatch):
    """Stop the route from starting the background task, so a test can run it by hand."""
    monkeypatch.setattr("app.routes.jobs.process_job", lambda job_id: None)
