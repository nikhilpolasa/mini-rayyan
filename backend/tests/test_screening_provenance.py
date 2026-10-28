"""Every rule outcome names a metadata field or a bounded algorithm match."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.screening import screen
from app.services import pipeline
from app import models as m
from .test_pipeline import save, pull, run
from scripts.screening_report import summarize

ROOT = Path(__file__).resolve().parents[2]
BASE = {"title": "Walking and sleep trial", "abstract": "Adults completed walking sessions and sleep quality was measured.", "language": "eng", "mesh": ["Humans"], "pub_types": ["Journal Article"], "query_groups": [["walking"], ["sleep"]]}
TAG = re.compile(r" \[(?:metadata: [^\]]+|algorithm: [^\]]+, matched '[^']*')\]$")


@pytest.mark.parametrize("updates, active, label, source, evidence", [
    ({"mesh": ["Animals"]}, ["non_human"], "exclude", "metadata", "mesh=Animals"),
    ({"mesh": [] , "title": "Walking and sleep in mice"}, ["non_human"], "exclude", "algorithm", "mice"),
    ({"mesh": ["Animals", "Humans"]}, ["non_human"], "include", "algorithm", "query_groups"),
    ({"language": ["deu", "fre"]}, ["non_english"], "exclude", "metadata", "language=deu,fre"),
    ({"language": ["eng", "fre"]}, ["non_english"], "include", "algorithm", "query_groups"),
    ({"language": None, "abstract": "Les adultes ont suivi une intervention de marche et de sommeil pendant plusieurs semaines."}, ["non_english"], "exclude", "algorithm", "langdetect"),
    ({"language": None, "abstract": "123"}, ["non_english"], "maybe", "algorithm", "langdetect"),
    ({"pub_types": ["Case Reports"]}, ["case_report"], "exclude", "metadata", "pub_types=Case Reports"),
    ({"pub_types": [], "title": "Walking and sleep: CASE-REPORT"}, ["case_report"], "exclude", "algorithm", "case_report_title"),
    ({"abstract": "An in silico simulation examined walking and sleep."}, ["simulation"], "exclude", "algorithm", "in silico"),
    ({"abstract": None}, ["no_abstract"], "maybe", "metadata", "abstract=missing"),
    ({"title": "非拉丁文字", "abstract": "步行和睡眠的研究以及其他内容。", "language": None}, ["non_english"], "maybe", "algorithm", "query_concept_gap"),
    ({"title": None, "abstract": None, "language": None, "mesh": None, "pub_types": None}, [], "maybe", "metadata", "abstract=missing"),
    ({}, [], "include", "algorithm", "query_groups"),
])
def test_provenance_edge_cases(updates, active, label, source, evidence):
    result = screen({**BASE, **updates}, active)
    assert result["label"] == label
    assert TAG.search(result["reason"]), result
    assert f"[{source}: " in result["reason"]
    assert evidence in result["reason"]


def test_fixture_report_counts_by_source_without_network():
    dataset = json.loads((ROOT / "fixtures" / "screening_synthetic.json").read_text(encoding="utf-8"))
    counts = summarize(dataset)
    assert set(counts) == {"non_human", "non_english", "case_report", "simulation", "no_abstract"}
    assert counts["non_human"]["metadata"] > 0
    assert counts["non_human"]["algorithm"] > 0
    assert counts["simulation"]["metadata"] == 0
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "screening_report.py")], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "synthetic-screening-80" in result.stdout


def test_rerun_replaces_old_cached_reason_without_touching_human_decisions(review, monkeypatch):
    client, factory, source = review
    monkeypatch.setattr(pipeline, "SCREEN_VERSION", "screen-v2")
    query = save(client, "first")
    pull(client, query)
    run(client, query)
    with factory.begin() as session:
        old = session.query(m.ScreenResult).filter_by(record_id=1).one()
        old.reason = "legacy reason without provenance"
    before = client.get("/api/decisions").json()
    monkeypatch.setattr(pipeline, "SCREEN_VERSION", "screen-v3")
    run(client, query)
    assert "[algorithm:" in client.get("/api/records/1").json()["reason"]
    assert client.get("/api/decisions").json() == before
    with factory() as session:
        assert session.query(m.ScreenResult).filter_by(record_id=1).count() == 2
