"""Add search-thread metadata without changing any existing evidence rows."""

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

from sqlalchemy import inspect, select

from .. import models as m
from ..db import Base, utc_now

LEGACY_TITLE = "Imported history (legacy)"


def _backup_sqlite(database: str) -> str | None:
    if database == ":memory:":
        return None
    source = Path(database).resolve()
    if not source.exists() or source.stat().st_size == 0:
        return None
    directory = source.parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{source.stem}.before-projects-{stamp}.db"
    target.touch(exist_ok=False)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original:
        with sqlite3.connect(target) as backup:
            original.backup(backup)
    return str(target)


def _backup_postgres(url) -> str:
    executable = shutil.which("pg_dump")
    if not executable:
        raise RuntimeError(
            "pg_dump is required before migrating an existing PostgreSQL database"
        )
    directory = Path("backups").resolve()
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"before-projects-{stamp}.dump"
    environment = os.environ.copy()
    for key, value in {
        "PGHOST": url.host,
        "PGPORT": url.port,
        "PGDATABASE": url.database,
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGSSLMODE": url.query.get("sslmode"),
    }.items():
        if value is not None:
            environment[key] = str(value)
    # Credentials stay in the child environment, never command arguments/output.
    subprocess.run(
        [executable, "--format=custom", "--file", str(target)],
        env=environment,
        check=True,
        capture_output=True,
    )
    if not target.exists() or not target.stat().st_size:
        raise RuntimeError("PostgreSQL backup is empty; migration was not started")
    return str(target)


def migrate_projects(engine, *, initialize_schema: bool = False) -> dict:
    """Idempotently create projects and import metadata; back up before writes.

    Stop the application before running the CLI migration. The application also
    calls this before create_all at startup, using its configured database only.
    """
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        existing = (
            set(connection.scalars(select(m.Project.id)))
            if "projects" in tables
            else set()
        )
        ids = {1}
        if "queries" in tables:
            ids.update(connection.scalars(select(m.Query.project_id).distinct()))
    missing = sorted(ids - existing)
    create = "projects" not in tables
    created_tables = sorted(
        (set(Base.metadata.tables) if initialize_schema else {"projects"}) - tables
    )
    if not created_tables and not missing:
        return {
            "created_table": False,
            "created_tables": [],
            "inserted_projects": [],
            "backup_path": None,
        }
    backup = None
    if engine.dialect.name == "sqlite":
        backup = _backup_sqlite(engine.url.database or ":memory:")
    elif engine.dialect.name == "postgresql":
        if tables:
            backup = _backup_postgres(engine.url)
    else:
        raise ValueError("Projects migration supports SQLite and PostgreSQL")
    with engine.begin() as connection:
        if initialize_schema:
            Base.metadata.create_all(connection)
        else:
            m.Project.__table__.create(connection, checkfirst=True)
        for id in missing:
            connection.execute(
                m.Project.__table__.insert().values(
                    id=id,
                    title=(
                        LEGACY_TITLE if id == 1 else f"Imported history (legacy {id})"
                    ),
                    created_at=utc_now(),
                )
            )
    return {
        "created_table": create,
        "created_tables": created_tables,
        "inserted_projects": missing,
        "backup_path": backup,
    }
