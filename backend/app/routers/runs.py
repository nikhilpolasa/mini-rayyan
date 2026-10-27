"""Run status, counts and durations for polling."""

from fastapi import APIRouter, Query
from sqlalchemy import select
from .. import models as m, schemas as s
from ..services.decisions import columns
from ._common import DB, require

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("", response_model=list[s.RunOut])
def list_runs(db: DB, query_id: int | None = Query(default=None, gt=0)):
    statement = select(m.RunLog).order_by(m.RunLog.id)
    if query_id is not None:
        require(db, m.Query, query_id)
        statement = statement.where(m.RunLog.query_id == query_id)
    return [columns(run) | {"counts": run.counts_json} for run in db.scalars(statement)]
