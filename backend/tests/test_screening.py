"""Screening rules, missing metadata, corpus labels and evaluator correctness."""

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from langdetect.lang_detect_exception import ErrorCode, LangDetectException

from app.services import screening as s
from fixtures.evaluate_screening import evaluate

ROOT = Path(__file__).resolve().parents[2]
DATASET = json.loads(
    (ROOT / "fixtures/screening_synthetic.json").read_text(encoding="utf-8")
)


def record(**updates):
    base = {
        "title": "Walking and sleep in adults",
        "abstract": "Adults completed walking sessions. Sleep quality was evaluated during eight weeks of follow-up.",
        "language": "eng",
        "mesh": ["Humans"],
        "pub_types": ["Journal Article"],
        "query_groups": [["walking", "exercise"], ["sleep"]],
    }
    return {**base, **updates}


@pytest.mark.parametrize(
    "updates",
    [
        {"mesh": ["Animals"]},
        {"mesh": [" animals "]},
        *[
            {
                "mesh": None,
                "abstract": f"A study of {term} examined laboratory outcomes.",
            }
            for term in [
                "rat",
                "rats",
                "mice",
                "mouse",
                "murine",
                "in vitro",
                "in-vitro",
                "zebrafish",
            ]
        ],
    ],
)
def test_non_human_metadata_and_keywords(updates):
    result = s.screen(record(**updates), ["non_human"])
    assert (
        result["label"] == "exclude"
        and result["criterion"] == "non_human"
        and result["reason"]
    )


@pytest.mark.parametrize(
    "updates",
    [
        {
            "mesh": ["Animals", "Humans"],
            "abstract": "Mice were discussed. Adults completed walking and sleep assessments.",
        },
        {"mesh": ["Humans"], "title": "Mouse-controlled walking and sleep assessment"},
        {"mesh": [], "title": "Walking and sleep ratios"},
        {"mesh": None, "title": "Walking and sleep saturation"},
        {
            "mesh": ["Humans"],
            "abstract": "An in vitro experiment motivated this walking and sleep trial in adults.",
        },
    ],
)
def test_non_human_metadata_precedence_and_boundaries(updates):
    assert s.screen(record(**updates), ["non_human"])["label"] == "include"


@pytest.mark.parametrize(
    "language", ["fre", "deu", "spa", "jpn", "rus", "FRE", ["deu", "fre"]]
)
def test_non_english_metadata(language):
    result = s.screen(record(language=language), ["non_english"])
    assert result["label"] == "exclude" and result["criterion"] == "non_english"


@pytest.mark.parametrize("language", ["eng", "ENG", "en", "English", ["eng", "fre"]])
def test_english_metadata_wins_over_detection(language, monkeypatch):
    monkeypatch.setattr(
        s, "detect_langs", lambda text: pytest.fail("Metadata must prevent detection")
    )
    assert s.screen(record(language=language), ["non_english"])["label"] == "include"


def test_language_fallback_real_detection_and_determinism():
    french = "Les participants adultes ont suivi un programme de marche pendant plusieurs semaines. La qualité du sommeil a été évaluée à plusieurs reprises. Les résultats ont été comparés à ceux du groupe témoin."
    english = "The adult participants completed a walking program for eight weeks. Sleep quality was measured before and after the intervention. The results were compared with those of a usual care group."
    assert (
        s.screen(record(language=None, abstract=french), ["non_english"])["label"]
        == "exclude"
    )
    assert (
        s.screen(record(language=None, abstract=english), ["non_english"])["label"]
        == "include"
    )
    results = [
        s.screen(record(language=None, abstract=french), ["non_english"])
        for _ in range(5)
    ]
    assert all(result == results[0] for result in results)


@pytest.mark.parametrize(
    "candidates",
    [
        [],
        [SimpleNamespace(lang="fr", prob=0.55)],
        [SimpleNamespace(lang="en", prob=0.55)],
    ],
)
def test_uncertain_language_never_excludes(candidates, monkeypatch):
    monkeypatch.setattr(s, "detect_langs", lambda text: candidates)
    result = s.screen(record(language=None), ["non_english"])
    assert result["label"] == "maybe" and result["criterion"] == "non_english"


def test_language_detection_failure_and_short_input(monkeypatch):
    def failure(text):
        raise LangDetectException(ErrorCode.CantDetectError, "Synthetic failure")

    monkeypatch.setattr(s, "detect_langs", failure)
    assert s.screen(record(language=None), ["non_english"])["label"] == "maybe"
    assert (
        s.screen(record(language=None, abstract="123456"), ["non_english"])["label"]
        == "maybe"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"pub_types": ["Case Reports"]},
        {"pub_types": ["Journal Article", "case reports"]},
        {"pub_types": "Case Report"},
        {"pub_types": None, "title": "Walking and sleep: a case report"},
        {"pub_types": [], "title": "Walking and sleep: two case reports"},
        {"title": "Walking and sleep: a CASE-REPORT"},
    ],
)
def test_case_report_metadata_and_title(updates):
    result = s.screen(record(**updates), ["case_report"])
    assert result["label"] == "exclude" and result["criterion"] == "case_report"


@pytest.mark.parametrize(
    "title",
    [
        "Walking and sleep case-control study",
        "Walking and sleep case reporting",
        "Walking and sleep showcase",
        "Walking and sleep report",
        "Walking and sleep case reportages",
    ],
)
def test_case_report_word_boundaries(title):
    assert s.screen(record(title=title), ["case_report"])["label"] == "include"


@pytest.mark.parametrize(
    "term",
    [
        "in silico",
        "IN SILICO",
        "in-silico",
        "Monte Carlo",
        "MONTE-CARLO",
        "simulation model",
        "simulation models",
        "computational model",
        "computational models",
        "simulation",
    ],
)
def test_simulation_keywords(term):
    result = s.screen(
        record(abstract=f"A {term} compared walking and sleep outcomes."),
        ["simulation"],
    )
    assert result["label"] == "exclude" and result["criterion"] == "simulation"


@pytest.mark.parametrize("abstract", [None, "", " ", "\n\t", 0, [], {}])
def test_no_abstract_is_maybe(abstract):
    assert s.screen(record(abstract=abstract), ["no_abstract"]) == {
        "label": "maybe",
        "reason": "no abstract",
        "criterion": "no_abstract",
    }


def test_no_abstract_safety_and_exclusions_outrank_maybe():
    assert s.screen(record(abstract=None), [])["label"] == "maybe"
    assert s.screen(record(abstract=None), [])["criterion"] == ""
    result = s.screen(
        record(abstract=None, pub_types=["Case Reports"]),
        ["no_abstract", "case_report"],
    )
    assert result["label"] == "exclude" and result["criterion"] == "case_report"


def test_active_criteria_order_unknown_keys_and_no_input_mutation():
    item = record(
        mesh=["Animals"],
        language="fre",
        pub_types=["Case Reports"],
        abstract="A computational model examined walking and sleep outcomes.",
    )
    original = copy.deepcopy(item)
    for key in ["non_human", "non_english", "case_report", "simulation"]:
        result = s.screen(item, [key])
        assert result["label"] == "exclude" and result["criterion"] == key
    assert s.screen(item, ["non_english", "non_human"])["criterion"] == "non_english"
    assert s.screen(item, ["non_human", "non_english"])["criterion"] == "non_human"
    assert s.screen(item, ["unknown_rule"])["label"] == "include"
    assert item == original


@pytest.mark.parametrize(
    "item",
    [
        {},
        {
            "title": None,
            "abstract": None,
            "mesh": None,
            "pub_types": None,
            "language": None,
        },
        {"title": 1, "abstract": [], "mesh": {}, "pub_types": 1, "language": {}},
        None,
    ],
)
def test_missing_or_malformed_fields(item):
    result = s.screen(item, list(s.CRITERIA))
    assert result["label"] == "maybe" and result["reason"]


@pytest.mark.parametrize("groups", [None, [], {}, [None], [[]], [[1, None]]])
def test_unknown_query_concepts_cannot_produce_include(groups):
    assert s.screen(record(query_groups=groups), [])["label"] == "maybe"


def test_relevance_uses_query_groups_without_topic_vocabulary():
    unrelated_topic = record(
        title="Ceramic coatings under thermal stress",
        abstract="A ceramic coating reduced thermal stress in the measured samples.",
        query_groups=[["polymer", "ceramic"], ["thermal stress"]],
    )
    assert s.screen(unrelated_topic, []) == {
        "label": "include",
        "reason": "matches all query concepts",
        "criterion": "",
    }
    unrelated_topic["query_groups"].append(["humidity", "moisture"])
    result = s.screen(unrelated_topic, [])
    assert result["label"] == "maybe" and "humidity OR moisture" in result["reason"]


def test_concept_matching_boundaries_phrases_and_wildcards():
    item = record(
        title="Walking trials and SLEEP quality", query_groups=[["trial"], ["sleep"]]
    )
    assert s.screen(item, [])["label"] == "maybe"


def test_unicode_query_concepts():
    item = record()
    item["query_groups"] = [["walk*"], ["SLEEP\tquality"]]
    assert s.screen(item, [])["label"] == "include"


def test_a_query_phrase_cannot_bridge_title_and_abstract():
    item = record(
        title="Walking in adults",
        abstract="Sleep quality was measured.",
        query_groups=[["adults sleep"]],
    )
    assert s.screen(item, [])["label"] == "maybe"
    item.update(
        title="ÉTUDE de marche et sommeil",
        abstract="Une étude a évalué la marche et le sommeil.",
        query_groups=[["étude"], ["sommeil"]],
    )
    assert s.screen(item, [])["label"] == "include"


@pytest.mark.parametrize("case", DATASET["cases"], ids=lambda case: case["id"])
def test_explicit_synthetic_reference_labels(case):
    predicted = s.screen(case["record"], case["active_criteria"])
    if case["baseline_limitation"]:
        # These labeled negative controls intentionally reveal documented rule limits.
        assert case["expected"]["label"] == "include"
        assert predicted["label"] == "exclude"
    else:
        assert {key: predicted[key] for key in ["label", "criterion"]} == case[
            "expected"
        ]
    assert set(predicted) == {"label", "reason", "criterion"}
    if predicted["label"] == "exclude":
        assert predicted["reason"] and predicted["criterion"] in case["active_criteria"]


def test_fixture_provenance_and_duplicates():
    assert len(DATASET["cases"]) == 80
    assert len({case["id"] for case in DATASET["cases"]}) == 80
    assert all(case["record"]["pmid"] is None for case in DATASET["cases"])
    assert any(ord(char) > 127 for char in DATASET["cases"][26]["record"]["abstract"])
    pairs = json.loads(
        (ROOT / "fixtures/duplicate_pairs.json").read_text(encoding="utf-8")
    )["pairs"]
    assert len(pairs) == 10 and {pair["expected"]["decision"] for pair in pairs} == {
        "auto",
        "pending",
        "none",
    }
    template = json.loads(
        (ROOT / "fixtures/pubmed_screening.template.json").read_text(encoding="utf-8")
    )
    assert template["cases"] == [] and all(
        value is None
        for value in template["case_template"]["criterion_matches"].values()
    )


def test_evaluator_counts_rules_independently_and_skips_unlabeled():
    both = record(mesh=["Animals"], language="fre")
    dataset = {
        "cases": [
            {
                "id": "both",
                "record": both,
                "active_criteria": ["non_human", "non_english"],
                "expected": {"label": "exclude", "criterion": "non_human"},
                "criterion_matches": {"non_human": True, "non_english": True},
            },
            {
                "id": "negative",
                "record": record(),
                "criterion_matches": {"non_human": False, "non_english": False},
            },
            {
                "id": "unreviewed",
                "record": both,
                "criterion_matches": {"non_human": None},
            },
        ]
    }
    report = evaluate(dataset)
    for key in ["non_human", "non_english"]:
        assert report["criteria"][key] == {
            "tp": 1,
            "fp": 0,
            "fn": 0,
            "tn": 1,
            "skipped": 1,
            "precision": 1.0,
            "recall": 1.0,
        }
    assert report["criteria"]["simulation"]["precision"] is None
    assert report["reviewed"] == 1


def test_evaluator_cli_outputs_metrics_and_rejects_unreviewed_template():
    result = subprocess.run(
        [sys.executable, str(ROOT / "fixtures/evaluate_screening.py"), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["case_count"] == report["reviewed"] == 80
    assert report["correct"] == 77 and len(report["disagreements"]) == 3
    assert report["criteria"]["simulation"]["fp"] == 1
    empty = subprocess.run(
        [
            sys.executable,
            str(ROOT / "fixtures/evaluate_screening.py"),
            str(ROOT / "fixtures/pubmed_screening.template.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert empty.returncode == 2 and "No reviewed" in empty.stdout
