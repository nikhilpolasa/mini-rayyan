"""Projected groups and uncertain pairs; records are never deleted."""

from fastapi import APIRouter
from .. import schemas as s
from ..services import dedup
from ._common import DB

router = APIRouter(prefix="/api/duplicates", tags=["duplicates"])


@router.get("", response_model=s.DuplicatesOut)
def list_duplicates(db: DB):
    state = dedup.state(db)
    return {"groups": state["groups"], "uncertain_pairs": state["uncertain_pairs"]}
