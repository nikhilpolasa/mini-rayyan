"""Seed fictional demo data in an empty database; never overwrite existing work."""

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app import models as m
from app.db import Base, SessionLocal, engine, utc_now
from app.services.criteria import ensure_criteria
from app.services.projects import migrate_projects


def seed_demo() -> None:
    """Insert three queries, ten synthetic records, a duplicate pair and decisions."""
    migrate_projects(engine, initialize_schema=True)
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as session:
        for table in Base.metadata.sorted_tables:
            if table.name == "projects":
                if any(row.id != 1 for row in session.scalars(select(m.Project))):
                    raise RuntimeError(
                        "Seed requires an empty database; existing searches were left untouched."
                    )
                continue  # The migration's empty legacy thread is safe to keep.
            if session.execute(select(table).limit(1)).first():
                raise RuntimeError(
                    "Seed requires an empty database; existing data was left untouched."
                )
        queries = []
        for version, text in enumerate(
            [
                "exercise[tiab] AND sleep[tiab]",
                "(exercise[tiab] OR walking[tiab]) AND sleep[tiab]",
                "exercise[tiab] AND sleep[tiab] AND adult[tiab]",
            ],
            start=1,
        ):
            query = m.Query(
                version=version,
                parent_id=queries[-1].id if queries else None,
                text=text,
                date_from=date(2016, 1, 1),
                date_to=date(2026, 10, 27),
                hit_count=10,
                query_translation=text,
                status="fetched",
            )
            session.add(query)
            session.flush()
            queries.append(query)
        records = []
        for index in range(1, 11):
            record = m.Record(
                pmid=f"DEMO-{index:04d}",
                doi=f"10.0000/demo.{1 if index == 2 else index}",
                title=f"Fictional exercise and sleep trial {1 if index == 2 else index}",
                abstract=(
                    None
                    if index == 10
                    else "Adults were assigned to exercise or usual care. Sleep quality was assessed after eight weeks."
                ),
                authors_json=["Example A", "Sample B"],
                year=2024,
                journal="Fictional Evidence Journal",
                language="eng",
                pub_types_json=["Randomized Controlled Trial"],
                mesh_json=["Humans", "Adult"],
                source="pubmed",
            )
            session.add(record)
            records.append(record)
        session.flush()
        for query in queries:
            session.add_all(
                [
                    m.QueryRecord(query_id=query.id, record_id=record.id)
                    for record in records
                ]
            )
        runs = {}
        for step, version in [
            ("dedup", "dedup-v1"),
            ("screen", "screen-v1"),
            ("pico", "pico-v1"),
        ]:
            run = m.RunLog(
                query_id=queries[0].id,
                step=step,
                rule_set_version=version,
                status="completed",
                counts_json={"records_in": 10, "seconds": 0.0},
                finished_at=utc_now(),
            )
            session.add(run)
            session.flush()
            runs[step] = run
        group = m.DupGroup(
            representative_record_id=records[0].id,
            dedup_version="dedup-v1",
            rule_set_version="dedup-v1",
            run_id=runs["dedup"].id,
        )
        session.add(group)
        session.flush()
        for record in records[:2]:
            session.add(
                m.GroupMember(
                    group_id=group.id,
                    record_id=record.id,
                    match_type="exact",
                    score=1.0,
                    status="auto",
                    dedup_version="dedup-v1",
                    rule_set_version="dedup-v1",
                    run_id=runs["dedup"].id,
                )
            )
        ensure_criteria(session)
        for record in records:
            if record is records[1]:
                continue  # The duplicate is hidden; demo machine outputs are prewritten fixtures.
            session.add(
                m.ScreenResult(
                    record_id=record.id,
                    rule_set_version="screen-v1",
                    label="maybe",
                    reason="Synthetic demo result; not screened.",
                    criterion="",
                    run_id=runs["screen"].id,
                )
            )
        session.add(
            m.PicoSpan(
                record_id=records[0].id,
                pico_version="pico-v1",
                label="P",
                start=0,
                end=6,
                text="Adults",
                source="machine",
                rule_set_version="pico-v1",
                run_id=runs["pico"].id,
            )
        )
        for entity_type, entity_id, action, old, new in [
            (
                "record",
                str(records[0].id),
                "set_label",
                {"label": "maybe"},
                {"label": "include"},
            ),
            (
                "group",
                str(group.id),
                "confirm",
                {"status": "auto"},
                {"status": "confirmed"},
            ),
            (
                "record",
                str(records[2].id),
                "set_label",
                {"label": "maybe"},
                {"label": "exclude"},
            ),
        ]:
            session.add(
                m.Decision(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=action,
                    old_value=old,
                    new_value=new,
                    note="Synthetic demo override.",
                    actor="reviewer",
                )
            )
    logging.info(
        "Seeded 3 queries, 10 fictional records, 1 duplicate pair and 3 decisions."
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_demo()
