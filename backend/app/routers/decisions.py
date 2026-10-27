"""Append-only human overrides and audit log."""

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from .. import models as m, schemas as s
from ..services import decisions, pipeline
from ._common import DB

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.post("", response_model=s.DecisionOut)
def create_decision(body: s.DecisionCreate, db: DB):
    with pipeline.job_lock:
        try:
            row = decisions.append_decision(db, body)
            db.commit()
            db.refresh(row)
            result = decisions.columns(row)
        except (ValueError, LookupError) as exc:
            db.rollback()
            raise HTTPException(
                404 if isinstance(exc, LookupError) else 422, str(exc)
            ) from None
        if (
            result["entity_type"] == "record"
            and isinstance(result["new_value"], dict)
            and result["new_value"].get("label") == "include"
        ):
            bind = db.get_bind()
            db.rollback()  # End refresh's read transaction; the decision is committed.
            try:
                pipeline.tag_included_record(int(result["entity_id"]), bind)
            except Exception as exc:
                # A failed machine step must never undo or misreport a saved decision.
                logging.error("Post-Include PICO failed (%s)", type(exc).__name__)
        return result


@router.get("", response_model=list[s.DecisionOut])
def list_decisions(db: DB):
    return [
        decisions.columns(row)
        for row in db.scalars(
            select(m.Decision).order_by(m.Decision.created_at, m.Decision.id)
        )
    ]
