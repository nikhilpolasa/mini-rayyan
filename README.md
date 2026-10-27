# Mini-Rayyan backend

The API persists immutable query versions, approvals, incremental PubMed fetches,
duplicate groups, machine results and append-only human decisions. OpenAPI is at
`/docs`; `Docs/api-examples.json` illustrates every endpoint's contract.
Screening, PICO and pair scoring still use their existing dummy implementations:
Maybe, no spans and no matches. The pipeline calls these modules without
duplicating their future algorithms. CSV exports effective, visible Includes.

From the repository root, on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts/reset_db.py
.\.venv\Scripts\python.exe scripts/seed_demo.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
```

Run tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini -q
```

From `backend/`, `uvicorn app.main:app --reload --port 8000` and `pytest -q`
also work with the environment activated. On macOS/Linux the virtualenv Python
is `.venv/bin/python`.

The default database is `sqlite:///./miniryan.db`, relative to the working
directory. Run database scripts and the app from the same directory or set an
absolute `DATABASE_URL`. The root `.env` is loaded by the database module.
`CORS_ORIGINS` accepts comma-separated origins. Set a real `NCBI_EMAIL` before
using live query creation/fetching. `FETCH_CAP` limits each query's pull (default
500). `SOURCE_MODE=live` selects PubMed; the snapshot adapter remains unimplemented
pending its format. Source failures return HTTP 503 on query creation or a failed
fetch run. PostgreSQL requires a suitable driver.

`reset_db.py` initializes an empty database and refuses populated databases;
it never deletes records. Set `DATABASE_URL` to a fresh database to start over.
`seed_demo.py` also refuses existing data. Its 3 queries, 10 records, duplicate
pair, and human decisions are entirely synthetic. The API reads the seeded data.
Frontend remains a placeholder.

Save a query, approve it, start its fetch, then poll its detail or `/api/runs`.
Once fetched, `POST /api/pipeline/run?query_id=...` queues dedup, screening, then
PICO. Background jobs create their own sessions and log counts and elapsed seconds.
Jobs run in-process with a local lock; they do not survive a process crash. Run a
single backend worker for this Level 1 implementation.

Machine versions include deterministic context hashes. Dedup covers all stored
records. Screen versions depend on the algorithm version and criteria settings;
records already screened under that version are reused across queries. PICO
versions also include the active query's concept groups. A new version appends
outputs. Unchanged reruns reuse outputs and preserve human decisions/spans.

The records API derives visibility from effective groups; nothing is deleted.
Human confirmations, rejections and group splits change that projection. A group
with conflicting human labels keeps all records visible with pending member
statuses. A later group label resolves the conflict.

Decision examples (all use `POST /api/decisions`):

- Record: `entity_type=record`, `entity_id=<record id>`, `action=set_label`,
  `new_value={"label":"include"}`; `action=note` only adds a note.
- Pair: `entity_type=pair`, `entity_id="1:2"`, `action=confirm` or `reject`.
  `merge` and `split` are accepted aliases. Pair IDs are sorted record IDs.
- Group: `entity_type=group`, `entity_id=<group id>`, `action=split`, `confirm`,
  or `set_label` with a label object. Labels apply to the group's records.
- PICO: `entity_type=pico_span`, `action=add`, `entity_id=<record id>`,
  `new_value={"record_id":1,"label":"P","start":0,"end":6,"text":"Adults"}`.
  For `relabel`/`remove`, use the target span ID. Human edits append new spans.
- `action=undo` with the same entity type/ID restores the latest decision's old
  value by appending another decision. `new_value` may be null for undo.

Unit tests use a temporary SQLite database and mocked HTTP/source clients, and
block live network calls. The opt-in live smoke script is
`backend/tests/manual_pubmed_smoke.py` and requires `NCBI_EMAIL`.
