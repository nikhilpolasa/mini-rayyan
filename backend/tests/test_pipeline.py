"""Review integration checks using real sessions and fake source/NLP services."""

import csv
import io

import pytest
from sqlalchemy import func, select

from app import models as m
from app.services import decisions, dedup, matching, pico, pipeline, screening


def save(client, text="first"):
    response = client.post(
        "/api/queries",
        json={"text": text, "date_from": "2016-01-01", "date_to": "2026-10-27"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def pull(client, id):
    assert client.post(f"/api/queries/{id}/approve").status_code == 200
    response = client.post(f"/api/queries/{id}/fetch")
    assert response.status_code == 200, response.text
    assert client.get(f"/api/queries/{id}").json()["status"] == "fetched"
    return response.json()


def run(client, id):
    response = client.post(f"/api/pipeline/run?query_id={id}")
    assert response.status_code == 200, response.text
    logs = client.get(f"/api/runs?query_id={id}").json()
    assert (
        next(log for log in logs if log["id"] == response.json()["run_id"])["status"]
        == "completed"
    ), logs
    return logs


def override(client, entity_type, entity_id, action="set_label", value=None):
    response = client.post(
        "/api/decisions",
        json={
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "new_value": value,
            "note": "Reviewer checked.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_query_versions_and_incremental_fetch(review):
    client, factory, source = review
    first = save(client)
    before = client.get(f"/api/queries/{first}").json()
    assert before["hit_count"] == 42 and before["translation"] == "translated: first"
    assert client.post(f"/api/queries/{first}/fetch").status_code == 409
    assert client.post(f"/api/pipeline/run?query_id={first}").status_code == 409
    pull(client, first)
    second = save(client, "second")
    query = client.get(f"/api/queries/{second}").json()
    assert query["version"] == 2 and query["parent_id"] == first
    pull(client, second)
    pull(client, second)
    assert source.fetches == [["1", "2"], ["3"]]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 3
        assert session.scalar(select(func.count()).select_from(m.QueryRecord)) == 4
        first_query = session.get(m.Query, first)
        assert (
            first_query.text,
            first_query.version,
            first_query.date_from.isoformat(),
            first_query.query_translation,
        ) == (before["text"], 1, before["date_from"], before["translation"])
    assert len(client.get("/api/queries").json()) == 2
    detail = client.get("/api/records/2").json()
    assert [q["version"] for q in detail["query_versions"]] == [1, 2]


def test_rerun_output_human_survival_and_record_count(review):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    run(client, id)
    override(client, "record", 1, value={"label": "include"})
    before = client.get("/api/records?show_hidden=true").json()
    audit = client.get("/api/decisions").json()
    with factory() as session:
        rows = [
            decisions.columns(row)
            for row in session.scalars(
                select(m.ScreenResult).order_by(m.ScreenResult.id)
            )
        ]
        count = session.scalar(select(func.count()).select_from(m.Record))
    logs = run(client, id)
    assert client.get("/api/records?show_hidden=true").json() == before
    assert client.get("/api/decisions").json() == audit
    with factory() as session:
        assert [
            decisions.columns(row)
            for row in session.scalars(
                select(m.ScreenResult).order_by(m.ScreenResult.id)
            )
        ] == rows
        assert session.scalar(select(func.count()).select_from(m.Record)) == count
    assert [log["step"] for log in logs[-4:]] == ["pipeline", "dedup", "screen", "pico"]
    assert all(log["finished_at"] and log["counts"]["seconds"] >= 0 for log in logs)
    assert (
        next(log for log in reversed(logs) if log["step"] == "screen")["counts"][
            "records_screened"
        ]
        == 0
    )
    assert (
        client.get("/api/records?label=include&limit=1&offset=0").json()["total"] == 1
    )


def test_dedup_visibility_pending_and_idempotence(review, monkeypatch):
    client, factory, source = review
    monkeypatch.setattr(
        matching,
        "pair_score",
        lambda a, b: (
            {"score": 1.0, "match_type": "exact"}
            if {a["pmid"], b["pmid"]} == {"1", "2"}
            else {"score": 0.9, "match_type": "fuzzy"}
        ),
    )
    id = save(client, "all")
    pull(client, id)
    run(client, id)
    duplicates = client.get("/api/duplicates").json()
    assert len(duplicates["groups"]) == 1
    assert len(duplicates["uncertain_pairs"]) == 2
    assert client.get("/api/records").json()["total"] == 2
    assert client.get("/api/records?show_hidden=true").json()["total"] == 3
    assert client.get("/api/records/2").json()["hidden_duplicate"] is True
    with factory() as session:
        assert list(
            session.scalars(
                select(m.ScreenResult.record_id).order_by(m.ScreenResult.record_id)
            )
        ) == [1, 3]
    run(client, id)
    assert client.get("/api/duplicates").json() == duplicates
    override(client, "pair", "1:3", "confirm")
    assert client.get("/api/records").json()["total"] == 1
    run(client, id)
    assert client.get("/api/records").json()["total"] == 1
    override(client, "group", duplicates["groups"][0]["id"], "split")
    assert client.get("/api/records").json()["total"] == 3


def test_query_groups_screening_pico_order_and_new_rule_versions(review, monkeypatch):
    client, factory, source = review
    calls = []

    def screen(record, active):
        calls.append(("screen", record, active))
        return {"label": "include", "reason": "Matched", "criterion": ""}

    def tag(text, terms):
        calls.append(("pico", text, terms))
        return [{"label": "P", "start": 0, "end": 6, "text": "Adults"}]

    monkeypatch.setattr(screening, "screen", screen)
    monkeypatch.setattr(pico, "tag_pico", tag)
    id = save(
        client,
        '("walking program"[tiab] OR exercise[tiab]) AND sleep[tiab] NOT animals[mesh]',
    )
    pull(client, id)
    run(client, id)
    assert [call[0] for call in calls] == ["screen"] * 3 + ["pico"] * 3
    assert calls[0][1]["query_groups"] == [["walking program", "exercise"], ["sleep"]]
    assert calls[-1][2] == ["walking program", "exercise", "sleep"]
    spans_before = client.get("/api/records/1").json()["pico_spans"]
    run(client, id)
    assert len(calls) == 6
    assert client.get("/api/records/1").json()["pico_spans"] == spans_before
    with factory.begin() as session:
        session.add(
            m.Criterion(
                key="non_human",
                label="Animal",
                kind="exclude",
                description="Animal studies",
                reason="Human question",
                source="both",
                active=True,
            )
        )
    run(client, id)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ScreenResult)) == 6
    override(client, "record", 1, value={"label": "exclude"})
    calls.clear()
    assert (
        client.patch("/api/criteria/non_human", json={"active": False}).status_code
        == 200
    )
    run(client, id)
    assert [call[0] for call in calls] == ["screen"] * 3 + ["pico"] * 2
    assert all(call[2] == [] for call in calls if call[0] == "screen")
    assert client.get("/api/records/1").json()["label"] == "exclude"


@pytest.mark.parametrize(
    "text,groups",
    [
        ('(a OR b) AND "c AND d"[tiab]', [["a", "b"], ["c AND d"]]),
        (
            "((adult[tiab] OR people[tiab]) AND sleep[tiab])",
            [["adult", "people"], ["sleep"]],
        ),
        ("sleep[tiab] NOT (animals[mesh] OR mice[tiab])", [["sleep"]]),
        (
            "major depressive disorder[tiab] AND placebo[tiab]",
            [["major depressive disorder"], ["placebo"]],
        ),
    ],
)
def test_query_groups(text, groups):
    assert pipeline.query_groups(text) == groups


def test_decision_undo_append_only_and_csv(review):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    run(client, id)
    decision = override(client, "record", 1, value={"label": "include"})
    response = client.get("/api/export.csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and rows[0]["abstract"] == source.records["1"]["abstract"]
    override(client, "record", 1, "undo")
    assert client.get("/api/records/1").json()["label"] == "maybe"
    audit = client.get("/api/decisions").json()
    assert audit[0] == decision and len(audit) == 2
    override(client, "record", 1, "undo")
    assert client.get("/api/records/1").json()["label"] == "include"


def test_pico_human_edits_and_rerun(review, monkeypatch):
    client, factory, source = review
    monkeypatch.setattr(
        screening,
        "screen",
        lambda record, active: {
            "label": "include",
            "reason": "Matched",
            "criterion": "",
        },
    )
    monkeypatch.setattr(
        pico,
        "tag_pico",
        lambda text, terms: [{"label": "P", "start": 0, "end": 6, "text": "Adults"}],
    )
    id = save(client)
    pull(client, id)
    run(client, id)
    original = client.get("/api/records/1").json()["pico_spans"][0]
    override(client, "pico_span", original["id"], "relabel", {"label": "I"})
    run(client, id)
    spans = client.get("/api/records/1").json()["pico_spans"]
    assert (
        len(spans) == 1 and spans[0]["source"] == "human" and spans[0]["label"] == "I"
    )
    override(client, "pico_span", original["id"], "remove")
    assert client.get("/api/records/1").json()["pico_spans"] == []
    override(client, "pico_span", original["id"], "undo")
    spans = client.get("/api/records/1").json()["pico_spans"]
    assert len(spans) == 1 and spans[0]["label"] == "I"
    with factory() as session:
        assert session.get(m.PicoSpan, original["id"]).source == "machine"


def test_failure_status_and_atomic_screen_step(review, monkeypatch):
    client, factory, source = review
    id = save(client)
    pull(client, id)

    def broken(record, active):
        if record["id"] == 2:
            raise RuntimeError("Synthetic failure")
        return {"label": "maybe", "reason": "Example", "criterion": ""}

    monkeypatch.setattr(screening, "screen", broken)
    client.post(f"/api/pipeline/run?query_id={id}")
    logs = client.get("/api/runs").json()
    assert [log["status"] for log in logs[-3:]] == ["failed", "completed", "failed"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.ScreenResult)) == 0
        assert session.scalar(select(func.count()).select_from(m.Record)) == 2

    def broken_fetch(pmids):
        raise RuntimeError("Synthetic source failure")

    source.fetch_records = broken_fetch
    second = save(client, "second")
    client.post(f"/api/queries/{second}/approve")
    client.post(f"/api/queries/{second}/fetch")
    assert client.get(f"/api/queries/{second}").json()["status"] == "failed"
    assert client.get("/api/runs").json()[-1]["status"] == "failed"


def test_conflicting_human_labels_are_not_hidden(review, monkeypatch):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    override(client, "record", 1, value={"label": "include"})
    override(client, "record", 2, value={"label": "exclude"})
    monkeypatch.setattr(
        matching, "pair_score", lambda a, b: {"score": 1.0, "match_type": "exact"}
    )
    run(client, id)
    assert client.get("/api/records").json()["total"] == 2
    group = client.get("/api/duplicates").json()["groups"][0]
    assert all(member["status"] == "pending" for member in group["members"])
    override(client, "group", group["id"], value={"label": "include"})
    assert client.get("/api/records").json()["total"] == 1


def test_http_errors_and_missing_entities(review):
    client, factory, source = review
    for url in [
        "/api/queries/99",
        "/api/records/99",
        "/api/records?query_id=99",
        "/api/runs?query_id=99",
    ]:
        assert client.get(url).status_code == 404
    assert (
        client.patch("/api/criteria/absent", json={"active": True}).status_code == 404
    )
    assert (
        client.post(
            "/api/decisions",
            json={
                "entity_type": "record",
                "entity_id": 99,
                "action": "set_label",
                "new_value": {"label": "include"},
            },
        ).status_code
        == 404
    )
    id = save(client)
    pull(client, id)
    assert (
        client.post(
            "/api/decisions",
            json={
                "entity_type": "record",
                "entity_id": 1,
                "action": "set_label",
                "new_value": {"label": "invalid"},
            },
        ).status_code
        == 422
    )
    with factory() as session:
        pipeline.enqueue(session, id, "pipeline")
    assert client.post(f"/api/pipeline/run?query_id={id}").status_code == 409


def test_rejected_pair_cannot_be_merged_transitively():
    assert dedup.components(
        [1, 2, 3], {(1, 2): {}, (1, 3): {}, (2, 3): {}}, {(1, 3)}
    ) == [[1, 2]]


def test_hidden_record_override_applies_to_group_and_group_split_undo(
    review, monkeypatch
):
    client, factory, source = review
    monkeypatch.setattr(
        matching, "pair_score", lambda a, b: {"score": 1.0, "match_type": "exact"}
    )
    id = save(client, "all")
    pull(client, id)
    run(client, id)
    override(client, "record", 2, value={"label": "include"})
    assert client.get("/api/records/1").json()["label"] == "include"
    group = client.get("/api/duplicates").json()["groups"][0]
    assert len(group["members"]) == 3
    override(client, "group", group["id"], "split")
    assert client.get("/api/records").json()["total"] == 3
    override(client, "group", group["id"], "undo")
    assert client.get("/api/records").json()["total"] == 1
    override(client, "pair", "3:1", "reject")
    assert client.get("/api/records").json()["total"] == 2
    assert len(client.get("/api/duplicates").json()["groups"]) == 1
    run(client, id)
    assert client.get("/api/records").json()["total"] == 2


def test_manual_pair_merge_and_undo_with_matching_stub(review):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    run(client, id)
    override(client, "pair", "2:1", "merge")
    groups = client.get("/api/duplicates").json()["groups"]
    assert len(groups) == 1 and client.get("/api/records").json()["total"] == 1
    run(client, id)
    assert client.get("/api/duplicates").json()["groups"] == groups
    override(client, "pair", "1:2", "undo")
    assert client.get("/api/records").json()["total"] == 2


def test_note_does_not_pin_machine_label_and_undo_restores_machine_control(
    review, monkeypatch
):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    run(client, id)
    override(client, "record", 1, "note")
    assert client.get("/api/records/1").json()["source"] == "machine"
    override(client, "record", 1, value={"label": "include"})
    override(client, "record", 1, "undo")
    assert client.get("/api/records/1").json()["source"] == "machine"
    monkeypatch.setattr(pipeline, "SCREEN_VERSION", "screen-v2")
    monkeypatch.setattr(
        screening,
        "screen",
        lambda record, active: {
            "label": "exclude",
            "reason": "Synthetic exclusion",
            "criterion": "test_rule",
        },
    )
    run(client, id)
    assert client.get("/api/records/1").json()["label"] == "exclude"


def test_pico_add_offsets_validation_and_undo(review):
    client, factory, source = review
    id = save(client)
    pull(client, id)
    bad = client.post(
        "/api/decisions",
        json={
            "entity_type": "pico_span",
            "entity_id": 2,
            "action": "add",
            "new_value": {
                "record_id": 2,
                "label": "P",
                "start": 0,
                "end": 6,
                "text": "Wrong!",
            },
        },
    )
    assert bad.status_code == 422
    override(
        client,
        "pico_span",
        2,
        "add",
        {"record_id": 2, "label": "P", "start": 0, "end": 6, "text": "Adults"},
    )
    assert len(client.get("/api/records/2").json()["pico_spans"]) == 1
    override(client, "pico_span", 2, "undo")
    assert client.get("/api/records/2").json()["pico_spans"] == []


def test_new_query_reuses_machine_results_and_human_exclusion(review, monkeypatch):
    client, factory, source = review
    calls = []

    def screen(record, active):
        calls.append(record["pmid"])
        return {"label": "maybe", "reason": "Uncertain", "criterion": ""}

    monkeypatch.setattr(screening, "screen", screen)
    first = save(client)
    pull(client, first)
    run(client, first)
    override(client, "record", 2, value={"label": "exclude"})
    second = save(client, "second")
    pull(client, second)
    run(client, second)
    assert calls == ["1", "2", "3"]
    assert client.get("/api/records/2").json()["label"] == "exclude"
    assert (
        client.get(f"/api/records?query_id={second}&label=exclude").json()["total"] == 1
    )
