"""Search threads; Phase A separates history, not reviewer judgments."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import models as m, schemas as s
from ..services import pipeline, decisions
from ._common import DB

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[s.ProjectOut])
def list_projects(db: DB):
    return [
        decisions.columns(row)
        for row in db.scalars(
            select(m.Project).order_by(m.Project.created_at.desc(), m.Project.id.desc())
        )
    ]


@router.post("", response_model=s.ProjectOut)
def create_project(body: s.ProjectCreate, db: DB):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Search title must not be blank")
    with pipeline.job_lock:
        for _ in range(3):
            # Explicit max+1 also avoids a Postgres sequence collision with the
            # imported project-1 ID, without changing/resetting any sequence.
            id = (db.scalar(select(func.max(m.Project.id))) or 0) + 1
            project = m.Project(id=id, title=title)
            db.add(project)
            try:
                db.commit()
                db.refresh(project)
                return decisions.columns(project)
            except IntegrityError:
                db.rollback()
    raise HTTPException(409, "Concurrent search creation; please retry")
