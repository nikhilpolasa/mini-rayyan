"""Criteria configuration; every toggle is recorded as a human decision."""

from fastapi import APIRouter
from sqlalchemy import select
from .. import models as m, schemas as s
from ..services import decisions, pipeline
from ._common import DB, require

router = APIRouter(prefix="/api/criteria", tags=["criteria"])


@router.get("", response_model=list[s.CriterionOut])
def list_criteria(db: DB):
    return [
        decisions.columns(row)
        for row in db.scalars(select(m.Criterion).order_by(m.Criterion.key))
    ]


@router.patch("/{key}", response_model=s.CriterionOut)
def update_criterion(key: str, body: s.CriterionPatch, db: DB):
    with pipeline.job_lock:
        criterion = require(db, m.Criterion, key)
        decisions.append_decision(
            db,
            s.DecisionCreate(
                entity_type="criterion",
                entity_id=key,
                action="toggle",
                new_value={"active": body.active},
            ),
        )
        db.commit()
        return decisions.columns(criterion)
