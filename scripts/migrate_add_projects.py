"""Back up and add search threads without altering existing rows.

Stop the backend, set DATABASE_URL, then run from the repository root:
python scripts/migrate_add_projects.py
SQLite backups include WAL data. Existing PostgreSQL requires pg_dump on PATH.
No URL or credentials are printed. A failed backup prevents migration writes.
"""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db import engine
from app.services.projects import migrate_projects

if __name__ == "__main__":
    try:
        print(json.dumps(migrate_projects(engine), indent=2))
    except Exception as exc:
        print(
            f"Migration stopped ({type(exc).__name__}); verify backup access and database configuration.",
            file=sys.stderr,
        )
        raise SystemExit(1)
