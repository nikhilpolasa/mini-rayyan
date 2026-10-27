"""Append-only human decisions and effective status/PICO projections."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import utc_now

LABELS = {"include", "exclude", "maybe"}


def columns(row) -> dict:
    """Serialize a mapped row without requiring ORM relationships."""
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def selected_version(
    session: Session, record_id: int, step: str, query_id: int | None = None
) -> str | None:
    """Select the latest completed processing version for a record's queries."""
    statement = (
        select(m.RunLog)
        .join(m.QueryRecord, m.QueryRecord.query_id == m.RunLog.query_id)
        .where(
            m.QueryRecord.record_id == record_id,
            m.RunLog.step == step,
            m.RunLog.status == "completed",
        )
        .order_by(m.RunLog.id.desc())
    )
    if query_id is not None:
        statement = statement.where(m.RunLog.query_id == query_id)
    run = next(
        (
            row
            for row in session.scalars(statement)
            if row.counts_json.get("record_id") in {None, record_id}
        ),
        None,
    )
    context = run.rule_set_version if run else None
    if context and step in {"screen", "pico"}:
        from .pipeline import _record_version

        record = session.get(m.Record, record_id)
        version = _record_version(context, record)
        model = m.ScreenResult if step == "screen" else m.PicoSpan
        if session.scalar(
            select(model.id)
            .where(
                model.record_id == record_id,
                model.rule_set_version == version,
            )
            .limit(1)
        ):
            return version
    # Preserve projections of pre-fix rows whose version was the run context.
    return context


def effective_status(
    session: Session,
    record_id: int,
    group_ids: set | None = None,
    version: str | None = None,
    peer_ids: set | None = None,
    query_id: int | None = None,
) -> dict:
    """Prefer the latest human label, otherwise the selected machine result."""
    human = list(
        session.scalars(
            select(m.Decision)
            .where(m.Decision.entity_type.in_(["record", "group"]))
            .order_by(m.Decision.created_at.desc(), m.Decision.id.desc())
        )
    )
    seen = set()
    for decision in human:
        applies = (
            decision.entity_type == "record"
            and int(decision.entity_id) in (peer_ids or {record_id})
        ) or (
            decision.entity_type == "group"
            and (
                int(decision.entity_id) in (group_ids or set())
                or (
                    isinstance(decision.new_value, dict)
                    and record_id in decision.new_value.get("record_ids", [])
                )
            )
        )
        if (
            applies
            and isinstance(decision.new_value, dict)
            and decision.new_value.get("label") in LABELS
        ):
            identity = (decision.entity_type, decision.entity_id)
            if identity in seen:
                continue
            seen.add(identity)
            if decision.new_value.get("source") == "machine":
                continue  # Suppress this entity's older labels after undo.
            return {
                "label": decision.new_value["label"],
                "reason": decision.new_value.get("reason", decision.note),
                "criterion": decision.new_value.get("criterion", ""),
                "source": "human",
            }
    version = version or selected_version(session, record_id, "screen", query_id)
    if query_id is not None and version is None:
        version = "unprocessed-query"
    statement = select(m.ScreenResult).where(m.ScreenResult.record_id == record_id)
    if version:
        statement = statement.where(m.ScreenResult.rule_set_version == version)
    machine = session.scalar(statement.order_by(m.ScreenResult.id.desc()))
    return {
        "label": machine.label if machine else "maybe",
        "reason": machine.reason if machine else "Not screened yet.",
        "criterion": machine.criterion if machine else "",
        "source": "machine",
    }


def effective_spans(
    session: Session, record_id: int, query_id: int | None = None
) -> list[dict]:
    """Overlay human span edits/removals without modifying original spans."""
    version = selected_version(session, record_id, "pico", query_id)
    if query_id is not None and version is None:
        version = "unprocessed-query"
    statement = select(m.PicoSpan).where(
        m.PicoSpan.record_id == record_id, m.PicoSpan.source == "machine"
    )
    if version:
        statement = statement.where(m.PicoSpan.rule_set_version == version)
    spans = {
        span.id: columns(span)
        for span in session.scalars(statement.order_by(m.PicoSpan.id))
    }
    for decision in session.scalars(
        select(m.Decision)
        .where(m.Decision.entity_type == "pico_span")
        .order_by(m.Decision.created_at, m.Decision.id)
    ):
        value = decision.new_value
        if not isinstance(value, dict) or value.get("record_id") != record_id:
            continue
        spans.pop(int(decision.entity_id), None)
        if isinstance(decision.old_value, dict) and decision.old_value.get("span_id"):
            spans.pop(decision.old_value["span_id"], None)
        if not value.get("removed") and value.get("span_id"):
            span = session.get(m.PicoSpan, value["span_id"])
            if span:
                spans[span.id] = columns(span)
    return sorted(
        spans.values(), key=lambda span: (span["start"], span["end"], span["id"])
    )


def validate_span(text: str, span: dict) -> None:
    """Reject invalid PICO labels or offsets against the exact stored abstract."""
    start, end = span.get("start"), span.get("end")
    if (
        span.get("label") not in {"P", "I", "C", "O"}
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= len(text)
        or text[start:end] != span.get("text")
    ):
        raise ValueError("PICO span must match its abstract text and offsets")


def append_decision(session: Session, body, actor: str = "reviewer") -> m.Decision:
    """Validate and append an override (including undo); never edit audit rows.

    Pair IDs are 'record_id:record_id'. For PICO add, entity_id is the record ID
    and new_value contains record_id/label/start/end/text. Other PICO actions use
    the span ID. Undo restores the latest decision's old value for that entity.
    """
    from . import dedup

    entity_type, entity_id, action = body.entity_type, str(body.entity_id), body.action
    if entity_type == "pair":
        try:
            ids = [int(id) for id in entity_id.split(":")]
            if len(ids) != 2:
                raise ValueError
            entity_id = dedup.pair_key(*ids)
        except ValueError:
            raise ValueError("Pair ID must be record_id:record_id") from None
    previous = session.scalar(
        select(m.Decision)
        .where(m.Decision.entity_type == entity_type, m.Decision.entity_id == entity_id)
        .order_by(m.Decision.created_at.desc(), m.Decision.id.desc())
    )
    value = body.new_value
    if action == "undo":
        if previous is None:
            raise ValueError("No decision to undo")
        value = previous.old_value
    old = None
    if entity_type == "record":
        record = session.get(m.Record, int(entity_id))
        if record is None:
            raise LookupError("Record not found")
        state = dedup.state(session)
        old = effective_status(
            session,
            record.id,
            state["membership"].get(record.id),
            peer_ids=state["peers"].get(record.id),
        )
        if action == "note":
            old, value = {"note": previous.note if previous else ""}, {
                "note": body.note
            }
        elif action == "undo" and isinstance(value, dict) and "note" in value:
            old = previous.new_value
        elif not isinstance(value, dict) or value.get("label") not in LABELS:
            raise ValueError("Record decisions require a valid label")
    elif entity_type in {"pair", "group"}:
        if entity_type == "pair":
            try:
                ids = sorted(int(id) for id in entity_id.split(":"))
            except ValueError:
                raise ValueError("Pair ID must be record_id:record_id") from None
            if (
                len(ids) != 2
                or ids[0] == ids[1]
                or any(session.get(m.Record, id) is None for id in ids)
            ):
                raise ValueError("Pair must reference two existing distinct records")
            entity_id = dedup.pair_key(*ids)
            member_ids = ids
        else:
            group = session.get(m.DupGroup, int(entity_id))
            if group is None:
                raise LookupError("Group not found")
            member_ids = list(
                session.scalars(
                    select(m.GroupMember.record_id).where(
                        m.GroupMember.group_id == group.id
                    )
                )
            )
        state = dedup.state(session)
        current = next(
            (
                group
                for group in state["groups"]
                if set(member_ids).issubset(
                    member["record_id"] for member in group["members"]
                )
            ),
            None,
        )
        old = (
            previous.new_value
            if previous
            else {"status": "auto" if current else "pending"}
        )
        if action == "undo":
            value = previous.old_value
        elif action in {"confirm", "merge", "reject", "split"}:
            value = {
                "status": "confirmed" if action in {"confirm", "merge"} else "rejected"
            }
        if not isinstance(value, dict) or (
            value.get("status") not in {"confirmed", "rejected", "pending", "auto"}
            and value.get("label") not in LABELS
        ):
            raise ValueError("Group/pair override requires a status or label")
        if entity_type == "pair" and "label" in value:
            raise ValueError("Pair decisions require a duplicate status")
        if entity_type == "group" and value.get("label") in LABELS:
            old = effective_status(session, min(member_ids), {int(entity_id)})
        if entity_type == "group":
            scope = (
                [member["record_id"] for member in current["members"]]
                if current
                else member_ids
            )
            value = {**value, "record_ids": value.get("record_ids", scope)}
            old_status = (
                (
                    "confirmed"
                    if any(
                        member["status"] == "confirmed" for member in current["members"]
                    )
                    else "auto"
                )
                if current
                else old.get("status", "pending")
            )
            old = {**old, "status": old_status, "record_ids": scope}
        if (
            entity_type == "pair"
            and value.get("status") == "confirmed"
            and current is None
        ):
            # Anchor a manually merged pair using its own human run, separate from machine runs.
            anchored = any(
                set(member_ids).issubset(
                    session.scalars(
                        select(m.GroupMember.record_id).where(
                            m.GroupMember.group_id == group.id
                        )
                    )
                )
                for group in session.scalars(select(m.DupGroup))
            )
            if not anchored:
                run = m.RunLog(
                    query_id=_record_query(session, member_ids[0]),
                    step="human_merge",
                    rule_set_version="human",
                    status="completed",
                    counts_json={"seconds": 0.0},
                    finished_at=utc_now(),
                )
                session.add(run)
                session.flush()
                group = m.DupGroup(
                    representative_record_id=min(member_ids),
                    dedup_version="human",
                    rule_set_version="human",
                    run_id=run.id,
                )
                session.add(group)
                session.flush()
                session.add_all(
                    [
                        m.GroupMember(
                            group_id=group.id,
                            record_id=id,
                            match_type="fuzzy",
                            score=1.0,
                            status="pending",
                            dedup_version="human",
                            rule_set_version="human",
                            run_id=run.id,
                        )
                        for id in member_ids
                    ]
                )
    elif entity_type == "criterion":
        criterion = session.get(m.Criterion, entity_id)
        if criterion is None:
            raise LookupError("Criterion not found")
        old = {"active": criterion.active}
        if not isinstance(value, dict) or type(value.get("active")) is not bool:
            raise ValueError("Criterion override requires active: boolean")
        criterion.active = value["active"]
    elif entity_type == "pico_span":
        target_id = int(entity_id)
        if action == "undo" and previous and isinstance(previous.new_value, dict):
            target_id = previous.new_value.get("span_id", target_id)
        span = None if action == "add" else session.get(m.PicoSpan, target_id)
        if action != "add" and span is None:
            raise LookupError("PICO span not found")
        record_id = (
            value.get("record_id")
            if action == "add" and isinstance(value, dict)
            else span.record_id if span else None
        )
        record = session.get(m.Record, record_id) if record_id else None
        if record is None:
            raise LookupError("Record not found")
        old = (
            previous.new_value
            if previous
            else (
                {**_span_value(span), "span_id": span.id}
                if span
                else {"record_id": record_id, "removed": True}
            )
        )
        if action == "remove":
            value = {"record_id": record_id, "removed": True}
        elif not isinstance(value, dict):
            raise ValueError("PICO override requires a span object")
        elif not value.get("removed"):
            data = {**(_span_value(span) if span else {}), **value}
            validate_span(record.abstract or "", data)
            human = m.PicoSpan(
                record_id=record_id,
                pico_version="human",
                rule_set_version="human",
                label=data["label"],
                start=data["start"],
                end=data["end"],
                text=data["text"],
                source="human",
                run_id=None,
            )
            session.add(human)
            session.flush()
            value = {**data, "record_id": record_id, "span_id": human.id}
    else:
        raise ValueError("Unknown decision entity")
    decision = m.Decision(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old,
        new_value=value,
        note=body.note,
        actor=actor,
    )
    session.add(decision)
    session.flush()
    return decision


def _span_value(span: m.PicoSpan) -> dict:
    """Keep audit JSON limited to editable fields, without datetime objects."""
    return {
        key: getattr(span, key)
        for key in ["record_id", "label", "start", "end", "text"]
    }


def _record_query(session: Session, record_id: int) -> int:
    """Find provenance for a manual pair merge."""
    query_id = session.scalar(
        select(m.QueryRecord.query_id)
        .where(m.QueryRecord.record_id == record_id)
        .limit(1)
    )
    if query_id is None:
        raise ValueError("Record must belong to a query before merging")
    return query_id
