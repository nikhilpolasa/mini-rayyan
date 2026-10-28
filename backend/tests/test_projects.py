"""Thread migration and legacy-compatible API checks in new temporary DBs."""

from datetime import date
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app import models as m
from app.db import Base
from app.services import projects


def legacy_database(path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(
        engine,
        tables=[
            table for table in Base.metadata.sorted_tables if table.name != "projects"
        ],
    )
    with Session(engine) as session:
        session.add(
            m.Query(
                id=10,
                project_id=1,
                version=7,
                parent_id=None,
                text="Legacy query",
                date_from=date(2020, 1, 1),
                date_to=date(2026, 1, 1),
            )
        )
        session.add(m.Record(id=20, pmid="LEGACY", title="Original evidence"))
        session.add(
            m.Decision(
                id=30,
                entity_type="record",
                entity_id="20",
                action="set_label",
                new_value={"label": "exclude"},
                note="Preserve judgment",
                actor="reviewer",
            )
        )
        session.add(
            m.Criterion(
                key="non_human",
                label="Custom",
                kind="exclude",
                description="Keep",
                reason="Keep",
                source="both",
                active=False,
            )
        )
        session.commit()
    return engine


def old_rows(engine):
    with engine.connect() as connection:
        return {
            table.name: list(connection.execute(table.select()).mappings())
            for table in Base.metadata.sorted_tables
            if table.name != "projects"
        }


def test_migration_backs_up_before_changes_and_preserves_every_legacy_row(tmp_path):
    engine = legacy_database(tmp_path / "legacy.db")
    before = old_rows(engine)
    try:
        result = projects.migrate_projects(engine)
        assert result["created_table"] and result["inserted_projects"] == [1]
        assert old_rows(engine) == before
        with sqlite3.connect(result["backup_path"]) as backup:
            assert backup.execute(
                "SELECT id,version,project_id FROM queries"
            ).fetchall() == [(10, 7, 1)]
            assert (
                backup.execute(
                    "SELECT name FROM sqlite_master WHERE name='projects'"
                ).fetchall()
                == []
            )
            assert backup.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 1
        with Session(engine) as session:
            assert session.get(m.Project, 1).title == projects.LEGACY_TITLE
            assert session.get(m.Criterion, "non_human").active is False
        assert projects.migrate_projects(engine) == {
            "created_table": False,
            "created_tables": [],
            "inserted_projects": [],
            "backup_path": None,
        }
        assert len(list((tmp_path / "backups").glob("*.db"))) == 1
    finally:
        engine.dispose()


def test_failed_backup_aborts_before_schema_changes(tmp_path, monkeypatch):
    engine = legacy_database(tmp_path / "legacy.db")
    before = old_rows(engine)

    def fail(_):
        raise OSError("Controlled backup failure")

    monkeypatch.setattr(projects, "_backup_sqlite", fail)
    try:
        with pytest.raises(OSError):
            projects.migrate_projects(engine)
        assert "projects" not in inspect(engine).get_table_names()
        assert old_rows(engine) == before
    finally:
        engine.dispose()


def test_cli_reports_changes_and_is_idempotent(tmp_path):
    path = tmp_path / "cli.db"
    engine = legacy_database(path)
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{path.as_posix()}"}
    command = [sys.executable, "scripts/migrate_add_projects.py"]
    root = Path(__file__).resolve().parents[2]
    try:
        first = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        result = json.loads(first.stdout)
        assert result["created_table"] and result["created_tables"] == ["projects"]
        assert Path(result["backup_path"]).exists()
        second = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert json.loads(second.stdout)["inserted_projects"] == []
    finally:
        engine.dispose()


def test_backup_includes_uncheckpointed_wal_rows(tmp_path):
    path = tmp_path / "wal.db"
    engine = legacy_database(path)
    try:
        with sqlite3.connect(path) as original:
            original.execute("PRAGMA journal_mode=WAL")
            original.execute("PRAGMA wal_autocheckpoint=0")
            original.execute("CREATE TABLE extra_evidence (text TEXT)")
            original.execute("INSERT INTO extra_evidence VALUES ('Keep WAL evidence')")
            original.commit()
            result = projects.migrate_projects(engine)
            with sqlite3.connect(result["backup_path"]) as backup:
                assert backup.execute("SELECT text FROM extra_evidence").fetchall() == [
                    ("Keep WAL evidence",)
                ]
    finally:
        engine.dispose()


def test_startup_schema_initialization_is_also_backed_up(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'partial.db').as_posix()}")
    try:
        projects.migrate_projects(engine)
        result = projects.migrate_projects(engine, initialize_schema=True)
        assert (
            result["created_table"] is False and "queries" in result["created_tables"]
        )
        with sqlite3.connect(result["backup_path"]) as backup:
            assert (
                backup.execute("SELECT title FROM projects").fetchone()[0]
                == projects.LEGACY_TITLE
            )
            assert (
                backup.execute(
                    "SELECT name FROM sqlite_master WHERE name='queries'"
                ).fetchall()
                == []
            )
    finally:
        engine.dispose()


def test_postgres_schema_and_backup_credentials(tmp_path, monkeypatch):
    assert "CREATE TABLE projects" in str(
        CreateTable(m.Project.__table__).compile(dialect=postgresql.dialect())
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(projects.shutil, "which", lambda _: "pg_dump")
    observed = []

    def dump(args, **kwargs):
        observed.append((args, kwargs))
        Path(args[-1]).write_bytes(b"controlled backup")

    monkeypatch.setattr(projects.subprocess, "run", dump)
    url = make_url("postgresql://reviewer:secret@localhost:5432/review?sslmode=require")
    assert Path(projects._backup_postgres(url)).exists()
    args, options = observed[0]
    assert "secret" not in " ".join(args)
    assert options["env"]["PGPASSWORD"] == "secret"
    assert options["env"]["PGSSLMODE"] == "require" and options["check"]
    monkeypatch.setattr(projects.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="pg_dump"):
        projects._backup_postgres(url)


def test_threads_restart_versions_and_reject_cross_thread_parents(review):
    client, factory, source = review

    def new(title):
        response = client.post("/api/projects", json={"title": title})
        assert response.status_code == 200
        return response.json()["id"]

    def save(project=None, parent="omit"):
        body = {
            "text": "alpha[tiab]",
            "date_from": "2020-01-01",
            "date_to": "2026-01-01",
        }
        if project is not None:
            body["project_id"] = project
        if parent != "omit":
            body["parent_id"] = parent
        return client.post("/api/queries", json=body)

    first, second = new("Diabetes"), new("Depression")
    a = save(first, None).json()
    b = save(second, None).json()
    revised = save(first, a["id"]).json()
    assert (a["version"], b["version"], revised["version"]) == (1, 1, 2)
    assert (
        client.get(f"/api/queries?project_id={first}").json()[1]["parent_id"] == a["id"]
    )
    assert [
        row["id"] for row in client.get(f"/api/queries?project_id={second}").json()
    ] == [b["id"]]
    calls = len(source.searches)
    assert save(first, b["id"]).status_code == 422
    assert save(999).status_code == 404 and len(source.searches) == calls
    legacy1, legacy2 = save().json(), save().json()
    assert legacy1["version"] == 1 and legacy2["version"] == 2
    detail = client.get(f"/api/queries/{legacy2['id']}").json()
    assert detail["project_id"] == 1 and detail["parent_id"] == legacy1["id"]
    assert (
        len(client.get("/api/queries").json()) == 5
    )  # Existing unfiltered GET default.
    assert [row["id"] for row in client.get("/api/projects").json()] == [
        second,
        first,
        1,
    ]
    assert client.post("/api/projects", json={"title": "   "}).status_code == 422
    with factory() as session:
        assert session.get(m.Query, a["id"]).version == 1


def test_new_threads_use_global_criteria(review):
    client, _, source = review
    project = client.post("/api/projects", json={"title": "Animals review"}).json()[
        "id"
    ]
    source.ids["alpha"] = ["1"]
    source.records["1"].update(
        title="Alpha study", mesh=["Animals"], abstract="Mice received alpha."
    )
    query = client.post(
        "/api/queries",
        json={
            "project_id": project,
            "text": "alpha",
            "date_from": "2020-01-01",
            "date_to": "2026-01-01",
        },
    ).json()["id"]
    client.post(f"/api/queries/{query}/approve")
    client.post(f"/api/queries/{query}/fetch")
    client.post(f"/api/pipeline/run?query_id={query}")
    row = client.get(f"/api/records/1?query_id={query}").json()
    assert row["label"] == "exclude" and row["criterion"] == "non_human"
