# Search threads Phase A

Maintainer-approved E7/CC2 scope: separate search histories and version counters,
not separate reviewer judgments. Work stops after Phase A. Phase B is not implemented.

## Behaviour

- New search creates a titled project/thread. Its first query is v1; Revise adds
  the next version in that same thread. Explicit parents from another thread fail.
- The sidebar lists threads newest first. Selecting one displays only its history,
  resets the query form, and clears a previous query selection. Parent descriptions
  use the version inside the selected thread, not a global query number.
- Route `project_id` is tab-local; query keys include it and the relevant query
  context. There is no global server-side current-project pointer.
- Long sentence input without field tags or Boolean operators gets a non-blocking
  keyword warning. This does not convert questions into PubMed syntax.
- Existing calls keep their prior defaults: POST queries without project_id uses
  project 1; omitted parent_id infers that project's latest query. Explicit null
  parent_id means no parent. GET queries without project_id remains unfiltered;
  the thread-aware frontend supplies project_id explicitly.
- No existing query IDs, versions, parents, text, dates, records or decisions are
  deleted, renumbered or rewritten. Existing history stays in project 1,
  **Imported history (legacy)**.

**Known limitation:** labels, notes, human PICO edits, duplicate state/visibility
and criteria remain shared across threads. The all-records view is explicitly
shared. A group representative linked only to another thread can still affect
global visibility. Phase B is needed to change this. Threads are not authentication
or isolated simultaneous judge sessions.

## Migration procedure

1. Stop the backend, use the same repository working directory and DATABASE_URL
   as the review being migrated. Do not run reset_db on a populated database.
2. From the repository root, run:

   ```powershell
   .\.venv\Scripts\python.exe scripts/migrate_add_projects.py
   ```

3. Inspect the JSON report: created tables, inserted project IDs and backup path.
   Existing SQLite files are backed up under an adjacent `backups/` directory
   before migration writes, using SQLite backup so uncheckpointed WAL data is
   retained. Existing PostgreSQL requires pg_dump on PATH; credentials are supplied
   in its environment, not command arguments or printed output. Backup failure
   aborts before migration writes.
4. Restart the backend. Startup uses the same backup-before-write path and creates
   missing tables safely. Repeating the migration is a no-op when metadata exists.
5. Open Imported history (legacy), confirm its old version numbers, then create
   a new titled search and save its v1. Revise that query to create v2.

The CLI adds only the projects metadata table/rows. Startup's shared helper can
also initialize missing application tables, backing up an existing file first.
It never alters existing table columns. New project IDs are allocated explicitly
without resetting PostgreSQL sequences or old IDs. Backup folders are ignored by
Git. No populated user database was migrated during this development task.

## Files changed

| Area | Files |
|---|---|
| Model, schema, startup | `backend/app/models.py`, `schemas.py`, `main.py` |
| Thread/query API | `backend/app/routers/projects.py`, `queries.py` |
| Migration and global criteria use | `backend/app/services/projects.py`, `pipeline.py` |
| Migration/init scripts | `scripts/migrate_add_projects.py`, `reset_db.py`, `seed_demo.py`, `.gitignore` |
| Backend tests | `backend/tests/test_projects.py`, `test_smoke.py` |
| UI, routes and cache keys | `frontend/src/App.tsx`, `pages.tsx`, `components.tsx`, `api.ts`, `types.ts`, `styles.css` |
| Mocks and examples | `frontend/src/mocks/mock.ts`, `api-examples.json`; `docs/api-examples.json` |
| Frontend tests | `frontend/src/search-threads.test.tsx`, `query-context.test.tsx`, `decision-refresh.test.tsx` |
| Documentation | `agents.md`, `docs/PRD.md`, `docs/design-decisions.md`, `README.md`, this report |

## Verification

| Check | Result |
|---|---|
| Full backend suite | 387 passed; one existing Starlette/httpx deprecation warning |
| Full frontend suite | 25 passed |
| TypeScript and production build | Passed |
| Legacy data migration | All pre-existing test-table rows unchanged; independent backup contains pre-migration data |
| WAL backup | Uncheckpointed test evidence present in backup |
| Migration idempotence/CLI | Repeated run reports no changes; CLI output exercised |
| Backup failure | No project table created; original rows unchanged |
| PostgreSQL checks | DDL compilation and mocked pg_dump credential/failure checks passed; actual server unverified |
| Thread/API behaviour | v1/v2 per project, same-project parent enforcement and old default calls passed |
| UI unit tests | New search, revision, separate histories/caches and warning behaviour passed in jsdom |
| Native browser, separate real tabs, live API, hosted database | Not verified in this task |

The five contracted rule/export signatures are unchanged. Phase A adds projects
metadata only; no decisions.project_id, project criteria key or Phase B visibility
projection was added. Passing unit/API tests is not browser acceptance.
