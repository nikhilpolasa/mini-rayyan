"""Mini-Rayyan API with persistent review state and in-process jobs."""

import os
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db  # Load the root .env before reading configuration.
from .services.criteria import ensure_criteria
from .routers import (
    criteria,
    decisions,
    duplicates,
    export,
    health,
    pipeline,
    queries,
    records,
    runs,
)


@asynccontextmanager
async def lifespan(application):
    # Use the normal DB provider, including an isolated test override when set.
    provider = application.dependency_overrides.get(db.get_db, db.get_db)
    with contextmanager(provider)() as session:
        db.Base.metadata.create_all(session.get_bind())
        ensure_criteria(session)
        session.commit()
    yield


app = FastAPI(
    title="Mini-Rayyan",
    version="0.0.1",
    description="Versioned literature searches and review pipeline.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

for module in (
    queries,
    pipeline,
    records,
    runs,
    duplicates,
    decisions,
    criteria,
    export,
    health,
):
    app.include_router(module.router)
