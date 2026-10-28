"""Scaffold contract checks; no external network or persistent database."""

import inspect as python_inspect
import csv
import io
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.db import Base
from app.main import app
from app.services.export import to_csv
from app.services.matching import normalize_title, pair_score
from app.services.pico import tag_pico
from app.services.pubmed import SnapshotSourceClient, SourceClient
from app.services.screening import screen

EXAMPLES = json.loads(
    (Path(__file__).resolve().parents[2] / "docs" / "api-examples.json").read_text(
        encoding="utf-8"
    )
)["endpoints"]


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_table_creation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "projects",
        "queries",
        "records",
        "query_records",
        "dup_groups",
        "group_members",
        "criteria",
        "screen_results",
        "pico_spans",
        "decisions",
        "run_log",
    }
    assert inspector.get_pk_constraint("query_records")["constrained_columns"] == [
        "query_id",
        "record_id",
    ]
    for table, columns in [
        ("records", ["pmid"]),
        ("queries", ["project_id", "version"]),
        ("screen_results", ["record_id", "rule_set_version"]),
    ]:
        assert columns in [
            item["column_names"] for item in inspector.get_unique_constraints(table)
        ]
    engine.dispose()


@pytest.mark.parametrize(
    "example", EXAMPLES, ids=lambda item: f'{item["method"]} {item["path"]}'
)
def test_endpoint_examples(example, api_client):
    response = api_client.request(
        example["method"], example["path"], json=example.get("request")
    )
    assert response.status_code == example["status_code"]
    assert response.headers["content-type"].startswith(example["content_type"])
    if example["content_type"] == "text/csv":
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert response.content.decode("utf-8-sig") == example["response"]
    else:
        # Examples define the contract; database state determines actual values.
        actual = response.json()
        expected = example["response"]
        assert type(actual) is type(expected)
        if isinstance(expected, dict):
            assert actual.keys() == expected.keys()
        elif expected and actual:
            assert actual[0].keys() == expected[0].keys()


def test_examples_cover_all_routes():
    # OpenAPI also verifies that the Pydantic contracts can generate a schema.
    operations = app.openapi()["paths"]
    assert sum(len(methods) for methods in operations.values()) == len(EXAMPLES)


@pytest.mark.parametrize(
    "record", [{}, {"doi": None, "abstract": None, "year": None, "journal": None}]
)
def test_service_contracts_with_missing_fields(record):
    assert screen(record, []) == {
        "label": "maybe",
        "reason": "no abstract",
        "criterion": "",
    }
    assert pair_score(record, record) == {"score": 0.0, "match_type": "none"}
    assert tag_pico("", []) == []
    assert normalize_title("Any Title") == "any title"
    exported = to_csv([record])
    assert exported.startswith(
        "\ufeffpmid,doi,title,abstract,year,journal,label,reason\r\n"
    )
    assert len(list(csv.DictReader(io.StringIO(exported.removeprefix("\ufeff"))))) == 1


def test_exact_service_signatures():
    for function, expected in [
        (screen, "(record: dict, active_criteria: list[str]) -> dict"),
        (tag_pico, "(text: str, query_terms: list[str]) -> list[dict]"),
        (normalize_title, "(title: str) -> str"),
        (pair_score, "(a: dict, b: dict) -> dict"),
        (to_csv, "(rows: list[dict]) -> str"),
    ]:
        assert str(python_inspect.signature(function)) == expected


@pytest.mark.parametrize("client_class", [SourceClient, SnapshotSourceClient])
def test_source_contracts_are_unimplemented(client_class):
    client = client_class()
    with pytest.raises(NotImplementedError):
        client.search_count("example", date(2020, 1, 1), date(2026, 1, 1))
    with pytest.raises(NotImplementedError):
        client.search_ids("example", date(2020, 1, 1), date(2026, 1, 1))
    with pytest.raises(NotImplementedError):
        client.fetch_records([])


def test_unique_pmid_and_utc_round_trip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(m.Record(pmid="DEMO-1", title="Fictional record"))
        session.commit()
        record = session.scalar(select(m.Record))
        assert record.fetched_at.utcoffset() == timedelta(0)
        session.add(m.Record(pmid="DEMO-1", title="Repeated PMID"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_input_validation_and_cors():
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/queries",
                json={
                    "text": "exercise",
                    "date_from": "2026-01-01",
                    "date_to": "2020-01-01",
                },
            ).status_code
            == 422
        )
        assert client.get("/api/records?limit=0").status_code == 422
        assert client.post("/api/pipeline/run").status_code == 422
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:5173"
        )


def test_reset_and_seed_preserve_existing_data(tmp_path, monkeypatch):
    from scripts import reset_db, seed_demo

    engine = create_engine(f"sqlite:///{(tmp_path / 'demo.db').as_posix()}")
    monkeypatch.setattr(reset_db, "engine", engine)
    monkeypatch.setattr(seed_demo, "engine", engine)
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(seed_demo, "SessionLocal", sessionmaker(bind=engine))
    reset_db.reset_db()
    seed_demo.seed_demo()
    with Session(engine) as session:
        assert len(session.scalars(select(m.Query)).all()) == 3
        assert len(session.scalars(select(m.Record)).all()) == 10
        assert len(session.scalars(select(m.QueryRecord)).all()) == 30
        assert len(session.scalars(select(m.GroupMember)).all()) == 2
        assert len(session.scalars(select(m.Decision)).all()) == 3
        assert len(session.scalars(select(m.Criterion)).all()) == 5
        assert all(row.active for row in session.scalars(select(m.Criterion)))
    with pytest.raises(RuntimeError, match="empty database"):
        seed_demo.seed_demo()
    with pytest.raises(RuntimeError, match="contains data"):
        reset_db.reset_db()
    with Session(engine) as session:
        assert len(session.scalars(select(m.Record)).all()) == 10
    engine.dispose()
