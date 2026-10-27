"""Release regressions using isolated databases and the real screening rules."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app import models as m
from app.db import Base
from app.main import app
from app.services import pipeline
from app.services.criteria import DEFAULTS
from backend.tests.test_pipeline import save, pull, run, override


@pytest.mark.parametrize("state", ["fresh", "populated_without_criteria", "disabled"])
def test_startup_inserts_only_missing_criteria(isolated_app_database, state):
    engine = isolated_app_database
    if state != "fresh":
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(m.Record(pmid="EXISTING", title="Preserve this evidence"))
            if state == "disabled":
                session.add(
                    m.Criterion(
                        key="non_human",
                        label="Reviewer label",
                        kind="exclude",
                        description="Reviewer description",
                        reason="Reviewer reason",
                        source="both",
                        active=False,
                    )
                )
            session.commit()
    for _ in range(2):
        with TestClient(app) as client:
            rows = {row["key"]: row for row in client.get("/api/criteria").json()}
            assert set(rows) == {row[0] for row in DEFAULTS}
            assert all(row["active"] for key, row in rows.items() if key != "non_human")
            assert rows["non_human"]["active"] is (state != "disabled")
            if state == "disabled":
                assert rows["non_human"]["label"] == "Reviewer label"
                assert rows["non_human"]["description"] == "Reviewer description"
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(m.Record)) == (
                state != "fresh"
            )
            assert session.scalar(select(func.count()).select_from(m.Decision)) == 0


def screen_count(logs):
    return next(row for row in reversed(logs) if row["step"] == "screen")["counts"][
        "records_screened"
    ]


@pytest.mark.parametrize(
    "concept,first_label,second_label",
    [("alpha", "include", "maybe"), ("beta", "maybe", "include")],
)
def test_query_context_cache_and_human_preservation(
    review, concept, first_label, second_label
):
    client, factory, source = review
    source.ids.update(alpha=["1", "2"], beta=["1", "2"])
    for data in source.records.values():
        data["abstract"] = (
            f"Adults received {concept} treatment. The primary outcome was symptom change."
        )
    first = save(client, "alpha")
    pull(client, first)
    assert screen_count(run(client, first)) == 2
    assert client.get("/api/records/1").json()["label"] == first_label
    override(client, "record", 2, value={"label": "exclude"})
    audit = client.get("/api/decisions").json()
    assert screen_count(run(client, first)) == 0
    second = save(client, "beta")
    pull(client, second)
    assert screen_count(run(client, second)) == 2
    assert client.get("/api/records/1").json()["label"] == second_label
    assert client.get("/api/records/2").json()["label"] == "exclude"
    assert client.get("/api/decisions").json() == audit
    assert screen_count(run(client, second)) == 0
    assert screen_count(run(client, first)) == 0
    assert client.get("/api/records/1").json()["label"] == first_label
    with factory() as session:
        rows = list(
            session.scalars(select(m.ScreenResult).where(m.ScreenResult.record_id == 1))
        )
        assert len(rows) == 2 and len({row.rule_set_version for row in rows}) == 2


def test_cache_invalidates_only_changed_records_configuration_and_algorithm(
    review, monkeypatch
):
    client, factory, source = review
    source.ids["alpha"] = ["1", "2"]
    for data in source.records.values():
        data["abstract"] = "Adults received alpha treatment."
    query = save(client, "alpha")
    pull(client, query)
    assert screen_count(run(client, query)) == 2
    with factory.begin() as session:
        session.get(m.Record, 1).abstract = "Adults received beta treatment."
    assert screen_count(run(client, query)) == 1
    assert client.get("/api/records/1").json()["label"] == "maybe"
    source.ids["alpha"].append("3")
    pull(client, query)
    assert screen_count(run(client, query)) == 1
    client.patch("/api/criteria/simulation", json={"active": False})
    assert screen_count(run(client, query)) == 3
    assert screen_count(run(client, query)) == 0
    monkeypatch.setattr(
        pipeline, "SCREEN_VERSION", pipeline.SCREEN_VERSION + "-changed"
    )
    assert screen_count(run(client, query)) == 3
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(m.Record)) == 3


def test_declared_criterion_precedence(review):
    client, _, source = review
    source.ids["alpha"] = ["1"]
    source.records["1"].update(
        title="Case report of alpha simulation in mice",
        language="deu",
        mesh=["Animals"],
        pub_types=["Case Reports"],
        abstract="Alpha simulation model in mice.",
    )
    query = save(client, "alpha")
    pull(client, query)
    for criterion in ["non_human", "non_english", "case_report", "simulation"]:
        run(client, query)
        row = client.get("/api/records/1").json()
        assert row["label"] == "exclude" and row["criterion"] == criterion
        client.patch(f"/api/criteria/{criterion}", json={"active": False})
