"""Initialize tables in an empty database without deleting existing data.

Run from the repo root: python scripts/reset_db.py
To start over, point DATABASE_URL at a new empty database. Existing populated
databases are refused to preserve the project's never-delete rule.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import inspect, select

from app import models  # Register every table.
from app.db import Base, engine
from app.services.projects import migrate_projects


def reset_db() -> None:
    """Create the schema only if the database has no existing rows."""
    existing = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if (
                table.name in existing
                and connection.execute(select(table).limit(1)).first()
            ):
                raise RuntimeError(
                    "Database contains data; use DATABASE_URL for a new empty database."
                )
    migrate_projects(engine, initialize_schema=True)
    Base.metadata.create_all(engine)
    logging.info(
        "Initialized %d tables without deleting data.", len(Base.metadata.tables)
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    reset_db()
