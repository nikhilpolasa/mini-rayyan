"""Level 2 group bridges, human conflicts and incremental machine work."""

from sqlalchemy import func, select
import os
import subprocess
import sys
from pathlib import Path

from app import models as m
from app.services import matching
from .test_pipeline import save, pull, run, override


def _bridge_source(source):
    titles = {1: "treatmant trial adults", 2: "treatmant trial adults", 3: "treatment trail adults", 4: "treatment trail adults", 5: "treatment trial adults"}
    for id in range(1, 6):
        source.records[str(id)] = {**source.records["1"], "pmid": str(id), "title": titles[id], "doi": "10.1/a" if id < 3 else "10.1/b" if id < 5 else None, "authors": ["Smith A"], "year": 2024, "journal": "Fictional Journal"}
    source.ids = {"first": ["1", "2", "3", "4"], "second": ["1", "2", "3", "4", "5"]}
    assert matching.pair_score(source.records["1"], source.records["3"])["match_type"] == "none"
    assert matching.pair_score(source.records["1"], source.records["5"])["score"] >= .95
    assert matching.pair_score(source.records["3"], source.records["5"])["score"] >= .95


def test_bridge_conflict_and_explicit_resolution(review):
    client, factory, source = review
    _bridge_source(source)
    first = save(client, "first"); pull(client, first); run(client, first)
    assert len(client.get("/api/duplicates").json()["groups"]) == 2
    override(client, "record", 1, value={"label": "include"})
    override(client, "record", 3, value={"label": "exclude"})
    decisions_before = client.get("/api/decisions").json()
    second = save(client, "second"); pull(client, second); run(client, second)
    groups = client.get("/api/duplicates").json()["groups"]
    assert len(groups) == 1
    assert {member["record_id"] for member in groups[0]["members"]} == {1, 2, 3, 4, 5}
    assert all(member["status"] == "pending" for member in groups[0]["members"])
    assert client.get("/api/records").json()["total"] == 5
    assert client.get("/api/records/1").json()["label"] == "include"
    assert client.get("/api/records/3").json()["label"] == "exclude"
    assert client.get("/api/decisions").json()[:len(decisions_before)] == decisions_before
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 5
    override(client, "group", groups[0]["id"], value={"label": "include"})
    assert client.get("/api/records").json()["total"] == 1
    assert client.get("/api/records/3").json()["label"] == "include"


def test_bridge_with_agreeing_human_decisions(review):
    client, _, source = review
    _bridge_source(source)
    first = save(client, "first"); pull(client, first); run(client, first)
    override(client, "record", 1, value={"label": "include"})
    override(client, "record", 3, value={"label": "include"})
    second = save(client, "second"); pull(client, second); run(client, second)
    group = client.get("/api/duplicates").json()["groups"][0]
    assert all(member["status"] != "pending" for member in group["members"])
    assert client.get("/api/records").json()["total"] == 1
    assert client.get("/api/records/3").json()["label"] == "include"


def test_refound_human_exclusion_and_incremental_counts(review):
    client, factory, source = review
    first = save(client, "first"); pull(client, first); run(client, first)
    override(client, "record", 2, value={"label": "exclude"})
    prior_decisions = client.get("/api/decisions").json()
    second = save(client, "first")
    source.ids["first"] = ["1", "2", "3"]
    pull(client, second); run(client, second)
    assert source.fetches == [["1", "2"], ["3"]]
    assert client.get("/api/records/2").json()["label"] == "exclude"
    assert client.get("/api/decisions").json() == prior_decisions
    logs = client.get(f"/api/runs?query_id={second}").json()
    screen = next(log for log in logs if log["step"] == "screen")
    assert screen["counts"]["screened"] == 1
    assert screen["counts"]["reused"] == 2
    run(client, second)
    logs = client.get(f"/api/runs?query_id={second}").json()
    assert [log["counts"]["screened"] for log in logs if log["step"] == "screen"] == [1, 0]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 3
        assert session.scalar(select(func.count()).select_from(m.QueryRecord)) == 5
        assert session.scalar(select(func.count()).select_from(m.ScreenResult).where(m.ScreenResult.record_id == 2)) == 1


def test_changed_abstract_only_rescreens_that_record(review):
    client, factory, source = review
    query = save(client, "first"); pull(client, query); run(client, query)
    with factory.begin() as session:
        session.get(m.Record, 1).abstract += " A changed sentence."
    run(client, query)
    screen = [row for row in client.get(f"/api/runs?query_id={query}").json() if row["step"] == "screen"][-1]
    assert screen["counts"]["screened"] == 1
    assert screen["counts"]["reused"] == 1
    assert screen["counts"]["records_screened"] == 1


def test_changed_query_groups_rescreen_linked_records_only(review):
    client, factory, source = review
    first = save(client, "first"); pull(client, first); run(client, first)
    second = save(client, "second"); pull(client, second); run(client, second)
    screen = [row for row in client.get(f"/api/runs?query_id={second}").json() if row["step"] == "screen"][-1]
    assert screen["counts"]["screened"] == 2  # Query concepts changed for both linked records.
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ScreenResult).where(m.ScreenResult.record_id == 1)) == 1


def test_unchanged_included_records_reuse_pico_spans(review):
    client, _, source = review
    for id in ("1", "2"):
        source.records[id]["abstract"] = "Adults received first treatment compared with placebo. Primary outcome was change in symptoms."
    query = save(client, "first"); pull(client, query); run(client, query); run(client, query)
    pico_runs = [row for row in client.get(f"/api/runs?query_id={query}").json() if row["step"] == "pico"]
    assert pico_runs[0]["counts"]["tagged"] == 2
    assert pico_runs[1]["counts"]["tagged"] == 0
    assert pico_runs[1]["counts"]["tag_reused"] == 2


def test_loop_demo_script_refuses_populated_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "DATABASE_URL": "sqlite:///" + (tmp_path / "loop.db").as_posix()}
    command = [sys.executable, str(root / "scripts" / "seed_loop_demo.py")]
    first = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert "bridges two older groups" in first.stdout
    second = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
    assert second.returncode != 0
    assert "existing data was not changed" in second.stderr
