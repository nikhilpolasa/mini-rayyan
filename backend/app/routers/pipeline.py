"""Queue database-backed pipeline jobs."""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from .. import models as m, schemas as s
from ..services import pipeline
from ._common import DB, require

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/run", response_model=s.JobStarted)
def run_pipeline(
    background_tasks: BackgroundTasks, db: DB, query_id: int = Query(gt=0)
):
    require(db, m.Query, query_id)
    with pipeline.job_lock:
        try:
            run = pipeline.enqueue(db, query_id, "pipeline")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    background_tasks.add_task(pipeline.execute, run.id, db.get_bind())
    return {"query_id": query_id, "run_id": run.id, "status": "queued"}
