"""Related publications must not become fuzzy automatic duplicate groups."""

import pytest

from app.services.matching import AUTO_THRESHOLD, UNCERTAIN_THRESHOLD, pair_score
from backend.tests.test_pipeline import save, pull, run

BASE = {
    "pmid": "1",
    "doi": None,
    "title": "Randomized evaluation of a structured treatment programme for persistent symptoms in adults with chronic disease compared with usual care over twelve months",
    "authors": ["Smith A"],
    "year": 2024,
    "journal": "Fictional Trials",
    "pub_types": ["Journal Article"],
}
GUARDS = [
    {"title": prefix + BASE["title"]}
    for prefix in ["Erratum: ", "  cOrReCtIoN: ", "Comment on ", "Reply to "]
] + [
    {"pub_types": [kind]}
    for kind in ["Published Erratum", "Comment", "Retraction of Publication"]
]


@pytest.mark.parametrize("guard", GUARDS)
def test_related_report_is_uncertain_on_either_side(guard):
    report = {**BASE, "pmid": "2", **guard}
    for a, b in [(BASE, report), (report, BASE)]:
        result = pair_score(a, b)
        assert result["match_type"] == "fuzzy"
        assert UNCERTAIN_THRESHOLD <= result["score"] < AUTO_THRESHOLD


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize("identifier", ["pmid", "doi"])
def test_shared_identifier_still_exact(guard, identifier):
    a = {**BASE, identifier: "10.0000/shared" if identifier == "doi" else "1"}
    b = {**a, **guard}
    assert pair_score(a, b) == {"score": 1.0, "match_type": "exact"}


def test_normal_pair_still_auto_and_unrelated_titles_do_not_become_candidates():
    assert pair_score(BASE, {**BASE, "pmid": "2"}) == {
        "score": 1.0,
        "match_type": "fuzzy",
    }
    assert (
        pair_score(BASE, {**BASE, "pmid": "2", "title": "Erratum: unrelated topic"})[
            "match_type"
        ]
        == "none"
    )


def test_guard_routes_pair_to_pipeline_uncertain_queue(review):
    client, _, source = review
    source.ids["all"] = ["1", "2"]
    for pmid in ["1", "2"]:
        source.records[pmid].update({**BASE, "pmid": pmid})
    source.records["2"]["pub_types"] = ["Published Erratum"]
    query = save(client, "all")
    pull(client, query)
    run(client, query)
    duplicates = client.get("/api/duplicates").json()
    assert duplicates["groups"] == []
    assert len(duplicates["uncertain_pairs"]) == 1
    assert client.get("/api/records").json()["total"] == 2
