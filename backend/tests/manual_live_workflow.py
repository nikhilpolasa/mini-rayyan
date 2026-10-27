"""Manual live route/persistence check; no mocks and no abstract output.

Run from the repository root with .venv/Scripts/python.exe
backend/tests/manual_live_workflow.py. Uses a new, retained SQLite database,
never the configured application database. TestClient executes real background
tasks before returning the fetch response. Outbound TLS verification stays on.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="sertraline[tiab] AND placebo[tiab]")
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    path = (args.database or root / (
        "live-check-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".db"
    )).resolve()
    if path.exists():
        parser.error("Choose a new database path; existing data will not be modified")
    os.environ["DATABASE_URL"] = "sqlite:///" + path.as_posix()
    os.environ["SOURCE_MODE"] = "live"
    os.environ["FETCH_CAP"] = "3"
    sys.path.insert(0, str(root / "backend"))

    from fastapi.testclient import TestClient
    from app.db import Base, engine
    from app import models  # Register all tables before create_all.
    from app.main import app

    Base.metadata.create_all(engine)
    result = {"database": str(path), "source": "live", "fetch_cap": 3,
              "transport": "in-process real FastAPI routes; real outbound HTTPX",
              "steps": [], "success": False}

    def request(client, method, endpoint, **kwargs):
        response = client.request(method, endpoint, **kwargs)
        result["steps"].append({"endpoint": endpoint, "http_status": response.status_code})
        if not response.is_success:
            # Do not print HTTP exception strings or credential-bearing URLs.
            raise RuntimeError("API request failed")
        return response.json()

    try:
        with TestClient(app) as client:
            created = request(client, "POST", "/api/queries", json={
                "text": args.query, "date_from": "2016-01-01",
                "date_to": datetime.now(timezone.utc).date().isoformat(),
            })
            result["query"] = created
            query_id = created["id"]
            request(client, "POST", f"/api/queries/{query_id}/approve")
            job = request(client, "POST", f"/api/queries/{query_id}/fetch")
            runs = request(client, "GET", f"/api/runs?query_id={query_id}")
            result["fetch_run"] = next(run for run in runs if run["id"] == job["run_id"])
            detail = request(client, "GET", f"/api/queries/{query_id}")
            page = request(client, "GET", f"/api/records?query_id={query_id}&show_hidden=true")
            result["query_status"] = detail["status"]
            result["api_record_count"] = page["total"]
            result["pmids"] = [row["pmid"] for row in page["items"]]
    except Exception as exc:
        result["error_type"] = type(exc).__name__
    finally:
        engine.dispose()
        # Reopen the file independently to prove persisted, committed rows.
        with sqlite3.connect(path) as connection:
            result["saved_record_count"] = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            result["query_record_links"] = connection.execute("SELECT COUNT(*) FROM query_records").fetchone()[0]
            result["saved_query_count"] = connection.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
        result["success"] = (
            "error_type" not in result
            and result.get("query_status") == "fetched"
            and result.get("fetch_run", {}).get("status") == "completed"
            and result["saved_record_count"] > 0
            and result["saved_record_count"] == result["query_record_links"] == result.get("api_record_count")
        )
        print(json.dumps(result, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
