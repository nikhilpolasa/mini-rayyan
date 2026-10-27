"""Human Include is committed before isolated automatic PICO transactions."""

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import pico
from backend.tests.test_pipeline import save, pull, override


def prepare(review):
    client, factory, source = review
    source.ids.update(alpha=["1", "2"], beta=["1", "2"])
    for data in source.records.values():
        data["abstract"] = (
            "Adults received alpha versus placebo. The primary outcome was symptom change."
        )
    queries = []
    for text in ["alpha", "beta"]:
        query = save(client, text)
        pull(client, query)
        queries.append(query)
    return client, factory, queries


def test_include_tags_without_pipeline_after_decision_commit(review, monkeypatch):
    client, factory, queries = prepare(review)
    original = pico.tag_pico
    checks, audit_sessions, machine_sessions = [], set(), set()

    def inspect_commit(text, terms):
        with factory() as independent:
            decision = independent.scalar(select(m.Decision))
            assert decision is not None and decision.new_value["label"] == "include"
            checks.append(decision.id)
        return original(text, terms)

    def inspect_flush(session, *_):
        if any(isinstance(row, m.Decision) for row in session.new):
            audit_sessions.add(id(session))
            assert not any(isinstance(row, m.PicoSpan) for row in session.new)
        if any(isinstance(row, m.PicoSpan) for row in session.new):
            machine_sessions.add(id(session))

    monkeypatch.setattr(pico, "tag_pico", inspect_commit)
    event.listen(Session, "before_flush", inspect_flush)
    try:
        saved = override(client, "record", 1, value={"label": "include"})
    finally:
        event.remove(Session, "before_flush", inspect_flush)
    assert checks == [saved["id"], saved["id"]]
    assert (
        audit_sessions
        and machine_sessions
        and audit_sessions.isdisjoint(machine_sessions)
    )
    assert client.get("/api/decisions").json() == [saved]
    for query in queries:
        detail = client.get(f"/api/records/1?query_id={query}").json()
        assert detail["source"] == "human" and detail["label"] == "include"
        assert detail["pico_spans"] and all(
            span["source"] == "machine" for span in detail["pico_spans"]
        )
        for span in detail["pico_spans"]:
            assert detail["abstract"][span["start"] : span["end"]] == span["text"]
        assert client.get(f"/api/records/2?query_id={query}").json()["pico_spans"] == []
        logs = client.get(f"/api/runs?query_id={query}").json()
        assert {run["step"] for run in logs} == {"fetch", "pico"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ScreenResult)) == 0
        count = session.scalar(select(func.count()).select_from(m.PicoSpan))
    override(client, "record", 1, value={"label": "include"})
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.PicoSpan)) == count
    assert client.get("/api/decisions").json()[0] == saved


def test_record_pico_run_does_not_replace_other_records_context(review):
    client, _, queries = prepare(review)
    override(client, "record", 1, value={"label": "include"})
    old = {
        query: client.get(f"/api/records/1?query_id={query}").json()["pico_spans"]
        for query in queries
    }
    client.patch("/api/criteria/simulation", json={"active": False})
    override(client, "record", 2, value={"label": "include"})
    for query in queries:
        assert (
            client.get(f"/api/records/1?query_id={query}").json()["pico_spans"]
            == old[query]
        )
        assert client.get(f"/api/records/2?query_id={query}").json()["pico_spans"]


def test_pico_failure_keeps_committed_include_and_logs_failure(review, monkeypatch):
    client, factory, queries = prepare(review)

    def fail(*_):
        raise RuntimeError("Controlled tagging failure")

    monkeypatch.setattr(pico, "tag_pico", fail)
    saved = override(client, "record", 1, value={"label": "include"})
    assert client.get("/api/decisions").json() == [saved]
    detail = client.get("/api/records/1").json()
    assert detail["label"] == "include" and detail["source"] == "human"
    assert detail["pico_spans"] == []
    assert any(
        row["step"] == "pico" and row["status"] == "failed"
        for row in client.get(f"/api/runs?query_id={queries[0]}").json()
    )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.PicoSpan)) == 0
