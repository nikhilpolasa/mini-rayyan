"""Provisional snapshot replay, with all outbound HTTP blocked by conftest."""

import json
import importlib.util
from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app import models as m
from app.services import pipeline, pubmed

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_articles.xml"
START, END = date(2016, 1, 1), date(2026, 10, 27)
REAL_SOURCE_CLIENT = pipeline.source_client
CAPTURE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_snapshot.py"


def snapshot_file(tmp_path, records, count=None):
    path = tmp_path / "provisional.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "queries": {
                    "exercise and care": {
                        "count": len(records) if count is None else count,
                        "pmids": [record["pmid"] for record in records],
                    }
                },
                "records": {record["pmid"]: record for record in records},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_snapshot_replays_saved_parser_fixture(tmp_path, monkeypatch):
    records = pubmed.parse_records(FIXTURE.read_bytes())
    monkeypatch.setenv("SNAPSHOT_PATH", str(snapshot_file(tmp_path, records)))
    source = pubmed.SnapshotSourceClient()
    assert source.search_count("  EXERCISE   and CARE ", START, END) == {
        "hit_count": 5,
        "translation": "exercise and care",
    }
    assert source.search_ids("EXERCISE AND CARE", START, END) == [
        record["pmid"] for record in records
    ]
    assert source.fetch_records([record["pmid"] for record in records]) == records


def test_snapshot_unknown_query_and_year_filter(tmp_path, monkeypatch):
    records = pubmed.parse_records(FIXTURE.read_bytes())
    monkeypatch.setenv("SNAPSHOT_PATH", str(snapshot_file(tmp_path, records)))
    source = pubmed.SnapshotSourceClient()
    assert source.search_count("unseen query", START, END) == {
        "hit_count": 0,
        "translation": "not in snapshot",
    }
    assert source.search_ids("unseen query", START, END) == []
    assert source.search_ids("exercise and care", date(2024, 1, 1), END) == [
        "100001", "100004", "100005"
    ]
    assert source.search_count("exercise and care", date(2024, 1, 1), END)[
        "hit_count"
    ] == 3
    assert source.search_ids("exercise and care", START, END, limit=1, offset=1) == [
        "100002"
    ]


def test_snapshot_partial_manifest_keeps_captured_count(tmp_path, monkeypatch):
    records = pubmed.parse_records(FIXTURE.read_bytes())[:2]
    monkeypatch.setenv("SNAPSHOT_PATH", str(snapshot_file(tmp_path, records, 42)))
    source = pubmed.SnapshotSourceClient()
    assert source.search_count("exercise and care", date(2024, 1, 1), END)[
        "hit_count"
    ] == 42
    assert source.search_ids("exercise and care", date(2024, 1, 1), END) == [
        "100001"
    ]


def test_snapshot_rejects_wrong_version(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text('{"version":2,"queries":{},"records":{}}', encoding="utf-8")
    monkeypatch.setenv("SNAPSHOT_PATH", str(path))
    with pytest.raises(ValueError, match="provisional snapshot format"):
        pubmed.SnapshotSourceClient()


def test_full_pipeline_from_snapshot_without_network(review, tmp_path, monkeypatch):
    client, factory, _ = review
    records = pubmed.parse_records(FIXTURE.read_bytes())
    monkeypatch.setenv("SNAPSHOT_PATH", str(snapshot_file(tmp_path, records)))
    monkeypatch.setenv("SOURCE_MODE", "snapshot")
    monkeypatch.setattr(pipeline, "source_client", REAL_SOURCE_CLIENT)

    created = client.post(
        "/api/queries",
        json={
            "text": "Exercise AND Care",
            "date_from": START.isoformat(),
            "date_to": END.isoformat(),
        },
    )
    assert created.status_code == 200, created.text
    query_id = created.json()["id"]
    assert created.json()["hit_count"] == 5
    assert client.post(f"/api/queries/{query_id}/approve").status_code == 200
    assert client.post(f"/api/queries/{query_id}/fetch").status_code == 200
    assert client.post(f"/api/pipeline/run?query_id={query_id}").status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 5
        assert session.scalar(select(func.count()).select_from(m.QueryRecord)) == 5
        steps = session.scalars(select(m.RunLog).order_by(m.RunLog.id)).all()
        assert [step.step for step in steps] == [
            "fetch", "pipeline", "dedup", "screen", "pico"
        ]
        assert all(step.status == "completed" for step in steps)


def test_capture_script_uses_live_client_without_network(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("make_snapshot", CAPTURE_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    records = pubmed.parse_records(FIXTURE.read_bytes())[:1]

    class FakeLive:
        fetch_cap = 1

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def search_count(self, *_):
            return {"hit_count": 42, "translation": "example"}

        def search_ids(self, *_, limit):
            assert limit == 1
            return [records[0]["pmid"]]

        def fetch_records(self, pmids):
            assert pmids == [records[0]["pmid"]]
            return records

    monkeypatch.setattr(script, "LiveSourceClient", FakeLive)
    queries = tmp_path / "queries.txt"
    queries.write_text("  EXERCISE  AND CARE  \n", encoding="utf-8")
    output = tmp_path / "captured.json"
    result = script.make_snapshot(queries, output, START, END)
    assert result == json.loads(output.read_text(encoding="utf-8"))
    assert result["queries"]["exercise and care"] == {
        "count": 42,
        "pmids": [records[0]["pmid"]],
    }

    def blocked(*_):
        raise httpx.ConnectError("blocked")

    monkeypatch.setattr(FakeLive, "search_count", blocked)
    with pytest.raises(RuntimeError, match="Live PubMed connection failed"):
        script.make_snapshot(queries, tmp_path / "no-output.json", START, END)
    assert not (tmp_path / "no-output.json").exists()
