"""Shared API projections; database rows stay separate from response contracts."""

from typing import Annotated
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models as m
from ..db import get_db
from ..services import decisions, dedup

DB = Annotated[Session, Depends(get_db)]


def require(session, model, id):
    row = session.get(model, id)
    if row is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return row


def query_created(query):
    return {
        "id": query.id,
        "version": query.version,
        "hit_count": query.hit_count,
        "translation": query.query_translation,
    }


def record_summaries(session, query_id=None, show_hidden=False, label=None):
    state = dedup.state(session)
    statement = select(m.Record).order_by(m.Record.id)
    if query_id is not None:
        require(session, m.Query, query_id)
        statement = statement.join(m.QueryRecord).where(
            m.QueryRecord.query_id == query_id
        )
    rows = []
    for record in session.scalars(statement):
        hidden = record.id in state["hidden"]
        if hidden and not show_hidden:
            continue
        status = decisions.effective_status(
            session,
            record.id,
            state["membership"].get(record.id),
            peer_ids=state["peers"].get(record.id),
            query_id=query_id,
        )
        if label and status["label"] != label:
            continue
        rows.append(
            {
                key: getattr(record, key)
                for key in ["id", "pmid", "doi", "title", "year", "journal"]
            }
            | status
            | {"hidden_duplicate": hidden}
        )
    return rows


def query_detail(session, query):
    rows = record_summaries(session, query.id, show_hidden=True)
    counts = {
        "records": len(rows),
        **{
            label: sum(
                row["label"] == label and not row["hidden_duplicate"] for row in rows
            )
            for label in ["include", "exclude", "maybe"]
        },
    }
    return decisions.columns(query) | query_created(query) | {"counts": counts}


def record_detail(session, record, query_id=None):
    if query_id is not None:
        require(session, m.Query, query_id)
        if session.get(m.QueryRecord, (query_id, record.id)) is None:
            raise HTTPException(404, "Record not found in this query")
    summary = next(
        row
        for row in record_summaries(session, query_id=query_id, show_hidden=True)
        if row["id"] == record.id
    )
    state = dedup.state(session)
    group = next(
        (
            group
            for group in state["groups"]
            if any(member["record_id"] == record.id for member in group["members"])
        ),
        None,
    )
    group_ids = state["membership"].get(record.id, set())
    audit = [
        decisions.columns(row)
        for row in session.scalars(select(m.Decision).order_by(m.Decision.id))
        if (row.entity_type == "record" and row.entity_id == str(record.id))
        or (row.entity_type == "group" and int(row.entity_id) in group_ids)
        or (row.entity_type == "pair" and str(record.id) in row.entity_id.split(":"))
        or (
            row.entity_type == "pico_span"
            and isinstance(row.new_value, dict)
            and row.new_value.get("record_id") == record.id
        )
    ]
    queries = session.scalars(
        select(m.Query)
        .join(m.QueryRecord)
        .where(m.QueryRecord.record_id == record.id)
        .order_by(m.Query.version)
    )
    return summary | {
        "abstract": record.abstract,
        "authors": record.authors_json,
        "language": record.language,
        "pub_types": record.pub_types_json,
        "mesh": record.mesh_json,
        "literature_source": record.source,
        "fetched_at": record.fetched_at,
        "pico_spans": decisions.effective_spans(session, record.id, query_id),
        "group": group,
        "decisions": audit,
        "query_versions": [query_created(query) for query in queries],
    }
