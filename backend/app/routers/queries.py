"""Immutable query versions and approval-gated background fetching."""

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .. import models as m, schemas as s
from ..services import pipeline
from ._common import DB, require, query_created, query_detail

router = APIRouter(prefix="/api/queries", tags=["queries"])


@router.post("", response_model=s.QueryCreated)
def create_query(body: s.QueryCreate, db: DB):
    if not body.text.strip():
        raise HTTPException(422, "Query text must not be blank")
    project_id = body.project_id or 1
    require(db, m.Project, project_id)
    if body.parent_id is not None:
        parent = require(db, m.Query, body.parent_id)
        if parent.project_id != project_id:
            raise HTTPException(422, "Parent query must belong to the same search")
    try:
        with pipeline.source_client() as client:
            count = client.search_count(body.text, body.date_from, body.date_to)
    except Exception as exc:
        # Avoid leaking credential-bearing HTTP URLs into API responses.
        raise HTTPException(
            503, "Source search failed; check source configuration and availability"
        ) from None
    with pipeline.job_lock:
        for attempt in range(3):
            latest = db.scalar(
                select(m.Query)
                .where(m.Query.project_id == project_id)
                .order_by(m.Query.version.desc())
                .limit(1)
            )
            query = m.Query(
                project_id=project_id,
                version=latest.version + 1 if latest else 1,
                parent_id=(
                    body.parent_id
                    if "parent_id" in body.model_fields_set
                    else latest.id if latest else None
                ),
                text=body.text,
                date_from=body.date_from,
                date_to=body.date_to,
                hit_count=count["hit_count"],
                query_translation=count["translation"],
                status="saved",
            )
            db.add(query)
            try:
                db.commit()
                db.refresh(query)
                return query_created(query)
            except IntegrityError:
                db.rollback()
        raise HTTPException(409, "Concurrent query save; please retry")


@router.get("", response_model=list[s.QueryDetail])
def list_queries(db: DB, project_id: int | None = Query(default=None, gt=0)):
    statement = select(m.Query).order_by(m.Query.version, m.Query.id)
    if project_id is not None:
        require(db, m.Project, project_id)
        statement = statement.where(m.Query.project_id == project_id)
    return [query_detail(db, query) for query in db.scalars(statement)]


@router.get("/{id}", response_model=s.QueryDetail)
def get_query(id: int, db: DB):
    return query_detail(db, require(db, m.Query, id))


@router.post("/{id}/approve", response_model=s.QueryApproval)
def approve_query(id: int, db: DB):
    query = require(db, m.Query, id)
    if query.status == "fetching":
        raise HTTPException(409, "Query is already fetching")
    if query.status != "fetched":
        query.status = "approved"
        db.commit()
    return {"id": query.id, "status": "approved"}


@router.post("/{id}/fetch", response_model=s.JobStarted)
def fetch_query(
    id: int,
    background_tasks: BackgroundTasks,
    db: DB,
    limit: int | None = Query(default=None, gt=0),
):
    require(db, m.Query, id)
    cap = max(0, int(os.getenv("FETCH_CAP", "500")))
    if limit is not None and limit > cap:
        raise HTTPException(
            422,
            f"Requested limit exceeds the server maximum ({cap}). "
            "Choose a smaller number or increase FETCH_CAP in the backend .env and restart.",
        )
    with pipeline.job_lock:
        try:
            run = pipeline.enqueue(db, id, "fetch", fetch_limit=limit)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    background_tasks.add_task(pipeline.execute, run.id, db.get_bind())
    return {"query_id": id, "run_id": run.id, "status": "queued"}
