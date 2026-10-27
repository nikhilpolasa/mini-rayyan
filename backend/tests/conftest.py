"""Isolated database/source fixtures; unit tests must never call live HTTP."""

from contextlib import contextmanager
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.db import Base, get_db
from app.main import app
from app.services import pipeline


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Unit tests may not contact live HTTP services")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


class FakeSource:
    def __init__(self):
        self.searches = []
        self.fetches = []
        self.ids = {"first": ["1", "2"], "second": ["2", "3"]}
        self.records = {
            str(id): {
                "pmid": str(id),
                "doi": None,
                "title": f"Fictional trial {id}",
                "abstract": 'Adults, with "symptoms"\nreceived care.',
                "authors": ["Example A"],
                "year": 2024,
                "journal": "Fictional Journal",
                "language": "eng",
                "pub_types": ["Journal Article"],
                "mesh": ["Humans"],
                "source": "pubmed",
            }
            for id in range(1, 5)
        }

    def search_count(self, text, date_from, date_to):
        self.searches.append((text, date_from, date_to))
        return {"hit_count": 42, "translation": f"translated: {text}"}

    def search_ids(self, text, date_from, date_to, limit=500, offset=0):
        return self.ids.get(text, ["1", "2", "3"])[offset : offset + limit]

    def fetch_records(self, pmids):
        self.fetches.append(list(pmids))
        return [self.records[id] for id in pmids if id in self.records]


@pytest.fixture
def review(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'review.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def get_session():
        with factory() as session:
            yield session

    source = FakeSource()

    @contextmanager
    def fake_source():
        yield source

    monkeypatch.setattr(pipeline, "source_client", fake_source)
    monkeypatch.setenv("FETCH_CAP", "500")
    app.dependency_overrides[get_db] = get_session
    with TestClient(app) as client:
        yield client, factory, source
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def api_client(review):
    """Seed API contract checks without contacting PubMed."""
    client, factory, source = review
    with factory.begin() as session:
        session.add(
            m.Query(
                id=1,
                version=1,
                text="first",
                date_from=date(2016, 1, 1),
                date_to=date(2026, 10, 27),
                hit_count=42,
                query_translation="translated: first",
                status="fetched",
            )
        )
        session.add(
            m.Criterion(
                key="non_human",
                label="Non-human studies",
                kind="exclude",
                description="Exclude animal-only studies.",
                reason="The review concerns humans.",
                source="both",
                active=True,
            )
        )
        session.flush()
        for id, data in source.records.items():
            record = pipeline._insert_record(session, data)
            session.add(m.QueryRecord(query_id=1, record_id=record.id))
    return client
