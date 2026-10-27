"""Mini-Rayyan API with persistent review state and in-process jobs."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db  # Load the root .env before reading configuration.
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

app = FastAPI(
    title="Mini-Rayyan",
    version="0.0.1",
    description="Versioned literature searches and review pipeline. NLP and matching services currently use contract stubs.",
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
