"""Effective record list and details, including duplicate visibility."""

from fastapi import APIRouter, Query
from .. import models as m, schemas as s
from ._common import DB, require, record_summaries, record_detail

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("", response_model=s.RecordPage)
def list_records(
    db: DB,
    query_id: int | None = Query(default=None, gt=0),
    label: s.Label | None = None,
    show_hidden: bool = False,
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
):
    rows = record_summaries(db, query_id, show_hidden, label)
    return {
        "items": rows[offset : offset + limit],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{id}", response_model=s.RecordDetail)
def get_record(id: int, db: DB, query_id: int | None = Query(default=None, gt=0)):
    return record_detail(db, require(db, m.Record, id), query_id)
