"""Application liveness."""

from fastapi import APIRouter
from .. import schemas as s

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=s.HealthOut)
def health():
    return {"status": "ok"}
