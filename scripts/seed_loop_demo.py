"""Seed a fictional two-version loop demo in a NEW, empty database only."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import inspect, select

from app import models as m
from app.db import Base, SessionLocal, engine
from app.services import criteria, pipeline


def seed_loop_demo() -> None:
    existing = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in existing and connection.execute(select(table).limit(1)).first():
                raise RuntimeError("Loop demo requires a new empty database; existing data was not changed")
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        criteria.ensure_criteria(session)
        query_text = "treatment[tiab] AND trial[tiab]"
        first = m.Query(version=1, text=query_text, date_from=date(2020, 1, 1), date_to=date(2026, 1, 1), hit_count=6, query_translation=query_text, status="fetched")
        session.add(first); session.flush()
        titles = {1: "treatmant trial adults", 2: "treatmant trial adults", 3: "treatment trail adults", 4: "treatment trail adults", 5: "treatment trial adults", 6: "treatment trial in mice", 7: "new treatment trial report"}
        records = []
        for id, title in titles.items():
            abstract = "Adults received treatment in a trial versus placebo. Primary outcome was symptom change." if id != 6 else "Mice received treatment in a trial."
            record = m.Record(id=id, pmid=f"LOOP-{id:04d}", doi="10.1/loop-a" if id < 3 else "10.1/loop-b" if id < 5 else None, title=title, abstract=abstract, authors_json=["Smith A"], year=2024, journal="Fictional Trials", language="eng", pub_types_json=["Journal Article"], mesh_json=["Animals"] if id == 6 else ["Humans"], source="synthetic")
            session.add(record); records.append(record)
        session.flush()
        for id in (1, 2, 3, 4, 6):
            session.add(m.QueryRecord(query_id=first.id, record_id=id))
        session.commit()
        pipeline.process(session, first)
        for id, label in ((1, "include"), (3, "exclude"), (6, "exclude")):
            session.add(m.Decision(entity_type="record", entity_id=str(id), action="set_label", old_value={"label": "maybe", "source": "machine"}, new_value={"label": label}, note="Fictional reviewer choice"))
        session.add(m.Decision(entity_type="record", entity_id="1", action="note", old_value={"note": ""}, new_value={"note": "Check design"}, note="Check design"))
        span = m.PicoSpan(record_id=1, pico_version="human", rule_set_version="human", label="I", start=16, end=25, text="treatment", source="human")
        assert records[0].abstract[16:25] == "treatment"
        session.add(span); session.flush()
        session.add(m.Decision(entity_type="pico_span", entity_id=str(span.id), action="add", old_value=None, new_value={"record_id": 1, "span_id": span.id, "label": "I", "start": 16, "end": 25, "text": "treatment"}, note="Fictional PICO correction"))
        second = m.Query(version=2, parent_id=first.id, text=query_text, date_from=first.date_from, date_to=first.date_to, hit_count=7, query_translation=query_text, status="fetched")
        session.add(second); session.flush()
        for id in (1, 2, 3, 4, 5, 6, 7):
            session.add(m.QueryRecord(query_id=second.id, record_id=id))
        session.commit()
        pipeline.process(session, second)
        print(f"Seeded fictional loop demo: v1 query {first.id}, v2 query {second.id}, {len(records)} stored records.")
        print("Click Queries: compare v2 with v1; v2 adds bridge record #5 and new record #7.")
        print("Click Records: excluded record #6 appears in both versions, keeps the human Exclude; inspect its query links and note/PICO edit on #1.")
        print("Click Duplicates: #5 bridges two older groups. #1 Include versus #3 Exclude leaves the merged group pending; resolve explicitly with a group decision.")


if __name__ == "__main__":
    seed_loop_demo()
