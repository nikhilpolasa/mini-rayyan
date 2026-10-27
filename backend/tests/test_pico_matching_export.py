"""Baseline PICO, bibliographic matching and CSV contract checks, without network."""

import codecs
import copy
import csv
import io
import json
from pathlib import Path

import pytest

from app.services import export, matching, pico


def paper(**updates):
    return {
        "pmid": None,
        "doi": None,
        "title": "Walking and sleep quality in adults: a randomized trial",
        "year": 2024,
        "authors": ["Smith Jane", "Jones Alex"],
        "journal": "Synthetic Journal",
        "pub_types": ["Journal Article"],
        **updates,
    }


@pytest.mark.parametrize(
    "title, expected",
    [
        ("  A   Clinical TRIAL! ", "a clinical trial"),
        ("Walking-and_sleep: quality?", "walking and sleep quality"),
        ("A\ntrial\twith  spaces", "a trial with spaces"),
        ("ÉTUDE / 健康", "étude 健康"),
        ("ＣＬＩＮＩＣＡＬ trial", "clinical trial"),
        ("Straße", "strasse"),
        ("!!!", ""),
        ("", ""),
        (None, ""),
        (123, ""),
    ],
)
def test_normalize_title(title, expected):
    assert matching.normalize_title(title) == expected
    assert matching.normalize_title(matching.normalize_title(title)) == expected


@pytest.mark.parametrize(
    "a,b",
    [
        (paper(doi=" 10.0000/EXAMPLE.1 "), paper(doi="10.0000/example.1")),
        (
            paper(doi="https://doi.org/10.0000/example.1"),
            paper(doi="doi:10.0000/example.1"),
        ),
        (
            paper(doi="http://dx.doi.org/10.0000/example.1"),
            paper(doi="10.0000/example.1"),
        ),
        (paper(pmid="12345"), paper(pmid=12345, title=None, year=None)),
        (paper(pmid="12345", doi="10.0000/a"), paper(pmid="12345", doi="10.0000/b")),
    ],
)
def test_pair_score_exact_identifiers(a, b):
    assert matching.pair_score(a, b) == {"score": 1.0, "match_type": "exact"}


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"title": "Walking and sleep quality in adults - a randomized trial"},
        {"year": 2023},
        {"year": "2025"},
        {"authors": ["SMITH Janet"]},
        {"authors": [{"last_name": "Smith"}]},
        {"journal": None},
    ],
)
def test_pair_score_automatic_fuzzy(updates):
    result = matching.pair_score(paper(), paper(**updates))
    assert (
        result["match_type"] == "fuzzy" and result["score"] >= matching.AUTO_THRESHOLD
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"year": None},
        {"year": 2018},
        {"year": "unknown"},
        {"authors": []},
        {"authors": None},
        {"authors": [","]},
        {"authors": ["Jones Jane"]},
        {"journal": "Different Journal"},
        {"pub_types": ["Congress"]},
        {"pub_types": ["Conference Paper"]},
        {"journal": "Annual Conference Proceedings"},
    ],
)
def test_pair_score_uncertain_metadata_or_conference(updates):
    result = matching.pair_score(paper(), paper(**updates))
    assert result["match_type"] == "fuzzy"
    assert matching.UNCERTAIN_THRESHOLD <= result["score"] < matching.AUTO_THRESHOLD


@pytest.mark.parametrize(
    "raw, expected_type, automatic",
    [
        (100, "fuzzy", True),
        (95, "fuzzy", True),
        (94.999, "fuzzy", False),
        (85, "fuzzy", False),
        (84.999, "none", False),
        (0, "none", False),
    ],
)
def test_pair_score_threshold_boundaries(raw, expected_type, automatic, monkeypatch):
    monkeypatch.setattr(matching.fuzz, "ratio", lambda a, b: raw)
    result = matching.pair_score(paper(), paper())
    assert result["match_type"] == expected_type
    assert (result["score"] >= matching.AUTO_THRESHOLD) is automatic


def test_pair_score_pages_tiebreaker_and_disagreeing_dois():
    result = matching.pair_score(
        paper(pages="12-18"), paper(journal="Journal Abbreviation", pages="12-18")
    )
    assert result["score"] >= matching.AUTO_THRESHOLD
    result = matching.pair_score(paper(pages="12-18"), paper(pages="29-35"))
    assert result["score"] < matching.AUTO_THRESHOLD
    assert (
        matching.pair_score(paper(doi="10.0000/1"), paper(doi="10.0000/2"))[
            "match_type"
        ]
        == "none"
    )


@pytest.mark.parametrize(
    "a,b",
    [
        ({}, {}),
        (paper(title=None), paper()),
        (paper(title=""), paper()),
        (None, None),
        (paper(title="Sleep patterns"), paper(title="Industrial water treatment")),
    ],
)
def test_pair_score_missing_or_unrelated_titles(a, b):
    result = matching.pair_score(a, b)
    assert (
        result["match_type"] == "none"
        and result["score"] < matching.UNCERTAIN_THRESHOLD
    )


def test_pair_score_symmetry_and_no_mutation():
    a, b = paper(year=2023), paper(year=2024, authors=["Smith John"])
    original = copy.deepcopy([a, b])
    assert matching.pair_score(a, b) == matching.pair_score(b, a)
    assert [a, b] == original


def test_pair_score_collective_authors_are_not_reduced_to_first_word():
    result = matching.pair_score(
        paper(authors=["International Sleep Study Group"]),
        paper(authors=["International Walking Study Group"]),
    )
    assert result["score"] < matching.AUTO_THRESHOLD


@pytest.mark.parametrize(
    "pair",
    json.loads(
        (
            Path(__file__).resolve().parents[2] / "fixtures/duplicate_pairs.json"
        ).read_text(encoding="utf-8")
    )["pairs"],
    ids=lambda pair: pair["id"],
)
def test_synthetic_duplicate_pairs(pair):
    result = matching.pair_score(pair["a"], pair["b"])
    decision = (
        "none"
        if result["match_type"] == "none"
        else (
            "auto"
            if result["match_type"] == "exact"
            or result["score"] >= matching.AUTO_THRESHOLD
            else "pending"
        )
    )
    assert decision == pair["expected"]["decision"]
    assert result["match_type"] == pair["expected"]["match_type"]


@pytest.mark.parametrize("text", [None, "", " ", "\n\t", 123, []])
def test_tag_pico_empty_or_missing_text(text):
    assert pico.tag_pico(text, []) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Adults with chronic fatigue received walking sessions.",
            "Adults with chronic fatigue",
        ),
        ("Patients with joint pain were enrolled.", "Patients with joint pain"),
        ("Children aged 8 to 12 were assigned to usual care.", "Children aged 8 to 12"),
        ("Participants were followed for eight weeks.", "Participants"),
        ("Healthy volunteers underwent exercise training.", "volunteers"),
    ],
)
def test_tag_pico_population(text, expected):
    spans = pico.tag_pico(text, [])
    assert any(span["label"] == "P" and span["text"] == expected for span in spans)


@pytest.mark.parametrize(
    "text, term",
    [
        ("Adults received walking sessions for eight weeks.", "walking sessions"),
        ("Patients were treated with light therapy versus placebo.", "light therapy"),
        (
            "Participants were assigned to exercise training or usual care.",
            "exercise training",
        ),
        (
            "Adults underwent mindfulness training after enrollment.",
            "mindfulness training",
        ),
        (
            "The intervention was virtual reality rehabilitation.",
            "virtual reality rehabilitation",
        ),
    ],
)
def test_tag_pico_query_driven_interventions(text, term):
    spans = pico.tag_pico(text, [term])
    assert any(span["label"] == "I" and term in span["text"] for span in spans)


@pytest.mark.parametrize(
    "comparator",
    ["placebo", "usual care", "control group", "waitlist", "wait-list", "wait list"],
)
def test_tag_pico_comparator_terms(comparator):
    spans = pico.tag_pico(f"Adults received treatment versus {comparator}.", [])
    assert any(span["label"] == "C" and comparator in span["text"] for span in spans)


@pytest.mark.parametrize("cue", ["versus", "vs.", "vs", "compared with", "compared to"])
def test_tag_pico_comparator_context_for_unseen_terms(cue):
    spans = pico.tag_pico(
        f"Adults received treatment {cue} neutral light exposure.",
        ["neutral light exposure"],
    )
    assert any(
        span["label"] == "C" and "neutral light exposure" in span["text"]
        for span in spans
    )


@pytest.mark.parametrize(
    "phrase",
    [
        "primary outcome",
        "change in sleep quality",
        "reduction in pain",
        "mean difference in mobility",
        "depression score",
    ],
)
def test_tag_pico_outcomes(phrase):
    spans = pico.tag_pico(f"The {phrase} was assessed after eight weeks.", [])
    assert any(span["label"] == "O" and phrase in span["text"] for span in spans)


@pytest.mark.parametrize(
    "text, terms",
    [
        (
            "🧪 Adults with fatigue received exercise versus placebo. The primary outcome was change in sleep score.",
            ["fatigue", "exercise", "sleep score"],
        ),
        (
            "Patients with α-thalassaemia received β-blockers. Mean difference in score was measured.",
            ["α-thalassaemia", "β-blockers"],
        ),
        (
            "Adults received A+B therapy compared with usual care. Reduction in pain was assessed.",
            ["A+B therapy"],
        ),
        (
            "ADULTS received light\ntherapy versus placebo.",
            ["light therapy", "light therapy"],
        ),
        ("Participants received therapy. Participants received therapy.", ["therapy"]),
        ("A completely unrelated sentence.", []),
    ],
)
def test_tag_pico_offsets_are_exact_deterministic_and_unique(text, terms):
    spans = pico.tag_pico(text, terms)
    assert spans == pico.tag_pico(text, terms)
    assert spans == sorted(
        spans, key=lambda span: (span["start"], span["end"], span["label"])
    )
    assert len(spans) == len(
        {(span["label"], span["start"], span["end"]) for span in spans}
    )
    for span in spans:
        assert span["label"] in {"P", "I", "C", "O"}
        assert text[span["start"] : span["end"]] == span["text"] and span["text"]


def test_tag_pico_query_boundaries_and_empty_terms():
    text = "A train crossed the city. Training followed later."
    spans = pico.tag_pico(text, ["train", "", None, "*", "[tiab]"])
    assert spans == [{"label": "I", "start": 2, "end": 7, "text": "train"}]


def test_tag_pico_population_query_terms_are_not_interventions():
    text = "Adults aged 18 to 65 with chronic fatigue received exercise."
    spans = pico.tag_pico(text, ["chronic fatigue", "exercise"])
    assert any(
        span["label"] == "P" and "chronic fatigue" in span["text"] for span in spans
    )
    assert not any(
        span["label"] == "I" and span["text"] == "chronic fatigue" for span in spans
    )


def parse_csv(value):
    return list(
        csv.DictReader(
            io.StringIO(value.encode("utf-8").decode("utf-8-sig"), newline="")
        )
    )


def test_to_csv_header_only_and_single_utf8_bom():
    result = export.to_csv([])
    assert isinstance(result, str)
    assert result.encode("utf-8").startswith(codecs.BOM_UTF8)
    assert result.count("\ufeff") == 1
    assert result.removeprefix("\ufeff") == ",".join(export.CSV_FIELDS) + "\r\n"
    assert parse_csv(result) == []


@pytest.mark.parametrize(
    "text",
    [
        "Title, with commas",
        'A "quoted" abstract',
        "First line\nSecond line",
        "First line\r\nSecond line",
        "ÉTUDE — 健康 🧪",
        " Leading and trailing spaces ",
    ],
)
def test_to_csv_round_trip_special_text(text):
    row = {"pmid": "DEMO-1", "title": text, "abstract": text, "label": "include"}
    result = parse_csv(export.to_csv([row]))
    assert result[0]["title"] == result[0]["abstract"] == text


def test_to_csv_missing_values_extra_columns_and_input_preservation():
    rows = [
        {"pmid": "DEMO-2", "doi": None, "year": None, "title": "", "extra": "ignored"},
        {},
    ]
    original = copy.deepcopy(rows)
    result = parse_csv(export.to_csv(rows))
    assert len(result) == 2 and set(result[0]) == set(export.CSV_FIELDS)
    assert result[0]["doi"] == result[0]["year"] == ""
    assert rows == original


def test_to_csv_preserves_order_and_serializes_selected_rows_without_filtering():
    rows = [{"pmid": "DEMO-3", "year": 2024}, {"pmid": "DEMO-1", "year": 2020}]
    result = parse_csv(export.to_csv(rows))
    assert [row["pmid"] for row in result] == ["DEMO-3", "DEMO-1"]
    assert [row["year"] for row in result] == ["2024", "2020"]


def test_to_csv_handles_missing_row_objects():
    assert len(parse_csv(export.to_csv([None, {}]))) == 2


def test_new_pipeline_versions_replace_cached_stub_outputs_without_losing_humans(
    review,
):
    from sqlalchemy import func, select
    from app import models as m
    from app.db import utc_now

    client, factory, source = review
    source.records["1"]["doi"] = source.records["2"]["doi"] = "10.0000/shared-fixture"
    created = client.post(
        "/api/queries",
        json={
            "text": "adults[tiab] AND care[tiab]",
            "date_from": "2016-01-01",
            "date_to": "2026-10-27",
        },
    )
    assert created.status_code == 200
    query_id = created.json()["id"]
    assert client.post(f"/api/queries/{query_id}/approve").status_code == 200
    assert client.post(f"/api/queries/{query_id}/fetch").status_code == 200
    with factory.begin() as session:
        old_run = m.RunLog(
            query_id=query_id,
            step="screen",
            rule_set_version="screen-v1-old-stub",
            status="completed",
            finished_at=utc_now(),
        )
        session.add(old_run)
        session.flush()
        for record in session.scalars(select(m.Record)):
            session.add(
                m.ScreenResult(
                    record_id=record.id,
                    run_id=old_run.id,
                    rule_set_version=old_run.rule_set_version,
                    label="maybe",
                    reason="Previous stub output",
                    criterion="",
                )
            )
    assert (
        client.post(
            "/api/decisions",
            json={
                "entity_type": "record",
                "entity_id": 3,
                "action": "set_label",
                "new_value": {"label": "exclude"},
                "note": "Reviewer exclusion",
            },
        ).status_code
        == 200
    )
    annotation = client.post(
        "/api/decisions",
        json={
            "entity_type": "pico_span",
            "entity_id": 1,
            "action": "add",
            "new_value": {
                "record_id": 1,
                "label": "P",
                "start": 0,
                "end": 6,
                "text": "Adults",
            },
            "note": "Reviewer population tag",
        },
    )
    assert annotation.status_code == 200
    audit_before = client.get("/api/decisions").json()
    for _ in range(2):
        job = client.post(f"/api/pipeline/run?query_id={query_id}")
        assert job.status_code == 200
        logs = client.get(f"/api/runs?query_id={query_id}").json()
        assert (
            next(run for run in logs if run["id"] == job.json()["run_id"])["status"]
            == "completed"
        )
        assert any(run["rule_set_version"].startswith("screen-v2-") for run in logs)
        assert any(run["rule_set_version"].startswith("pico-v2-") for run in logs)
        assert any(run["rule_set_version"].startswith("dedup-v3-") for run in logs)
        assert client.get("/api/records/1").json()["label"] == "include"
        assert client.get("/api/records/2").json()["hidden_duplicate"] is True
        assert client.get("/api/records/3").json()["label"] == "exclude"
        assert client.get("/api/records/3").json()["source"] == "human"
        assert any(
            span["source"] == "human"
            for span in client.get("/api/records/1").json()["pico_spans"]
        )
        assert client.get("/api/decisions").json() == audit_before
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 3
        assert (
            len(
                session.scalars(
                    select(m.ScreenResult).where(
                        m.ScreenResult.rule_set_version == "screen-v1-old-stub"
                    )
                ).all()
            )
            == 3
        )
        assert (
            len(
                session.scalars(
                    select(m.ScreenResult).where(
                        m.ScreenResult.rule_set_version.like("screen-v2-%")
                    )
                ).all()
            )
            == 2
        )
        assert all(
            row.reason == "Previous stub output"
            for row in session.scalars(
                select(m.ScreenResult).where(
                    m.ScreenResult.rule_set_version == "screen-v1-old-stub"
                )
            )
        )
