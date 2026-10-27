# Release blocker verification

Branch: `fix/blockers`. Scope: the four requested blockers only. No workspace implementation, public function signature change, API shape change or table-column change. Tests use new temporary SQLite databases. No populated developer database was reset, deleted or used by the test suite.

## Fixes and files

| Area | Files | Change |
|---|---|---|
| Criteria initialization | `backend/app/services/criteria.py`, `backend/app/main.py`, `scripts/seed_demo.py` | Share five baseline definitions; insert missing rows at startup and in an empty demo seed. Never overwrite existing rows or disabled flags. Startup creates missing tables without dropping or resetting anything. |
| Screening cache and projections | `backend/app/services/pipeline.py`, `backend/app/services/decisions.py` | Hash query concepts, ordered criterion configuration and algorithm version into the run context. Hash each record's exact content/metadata into its result version. Select those per-record versions in effective results, retaining compatibility with old rows. Apply the same per-record version derivation to PICO so its projections remain coherent. |
| Criterion order | `backend/app/services/pipeline.py` | Pass non_human, non_english, case_report, simulation, no_abstract in declared order, rather than sorting them alphabetically. |
| UI refresh | `frontend/src/components.tsx` | After a successful mutation, cancel outstanding reads before invalidating/refetching active and cached inactive queries. Old read responses cannot replace post-write data. |
| Regression and acceptance coverage | `backend/tests/test_blockers.py`, `backend/tests/test_acceptance.py`, `frontend/src/decision-refresh.test.tsx` | Cover startup preservation, context-sensitive reuse and the reproduced UI race; run the ten-step API acceptance flow using real rule functions. |
| Existing test integration | `backend/tests/conftest.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_smoke.py` | Isolate startup DB access, remove duplicate criterion inserts now supplied by startup, replace the obsolete expectation that different query concepts reuse the same machine result, and assert five seeded criteria. |

## UI failure reproduction and result

The minimal Vitest reproduction is a client-cache race, not a claim to have reproduced the user's exact browser session:

1. Mount list, record detail, duplicate and audit observers using the real frontend API transport and shared mutation hook.
2. Capture and delay the first list and audit GET responses, preserving their pre-decision snapshots.
3. Save a label override, confirm a pair, reject a pair or add a PICO edit while those reads are pending. The controlled transport commits each write.
4. Deliver the older GET snapshots after the mutation.
5. Assert list, detail, duplicate and audit observations equal the current stored state.

Before the fix, **all four cases failed**: the write succeeded but the audit/list could remain at the old snapshot. Invalidating an initial still-pending query did not guarantee another read. After cancelling pending reads before refetch, **all four pass**. Existing page tests also pass. No server projection defect was needed to reproduce this race. The real backend decision projections are independently exercised by the acceptance harness.

## Test results

| Check | Result |
|---|---|
| Full backend suite | 348 passed; one existing Starlette/httpx deprecation warning |
| Full frontend suite | 19 passed, including four new refresh regressions |
| Frontend production build | TypeScript and Vite build passed |
| Targeted backend blocker/pipeline/smoke run | 53 passed |
| Isolated PRD acceptance harness | All ten automated API/data steps passed |

New backend coverage includes three startup states (fresh DB, populated DB without criteria, existing disabled criterion), two Include/Maybe query-context cases, per-record content/configuration/algorithm invalidation, declared criterion precedence, and the end-to-end acceptance test. Existing record count and audit preservation checks remain in place.

## PRD section 15 acceptance results

Only the external source is controlled. The harness calls the real `screen`, `tag_pico` and `pair_score` through the real FastAPI routes and SQLAlchemy sessions. It uses eleven authored synthetic records in a newly created temporary database; it does not fetch new live PubMed data.

| Step | Automated assertions | Result and boundary |
|---|---|---|
| 1 | Save query v1 and receive count/translation. | PASS through API; browser display not exercised by this harness. |
| 2 | Save edited v2, list both, retain v1 and parent linkage. | PASS. |
| 3 | Approve/fetch both; fetch ten first, only one additional record second; retain 21 query-record links to eleven unique papers. | PASS with controlled source. |
| 4 | Form one exact and one fuzzy auto-group, expose uncertain pairs; hide two nonrepresentatives and recover all eleven with show-hidden. | PASS through API. |
| 5 | Screen every visible record; exercise all four exclusions and missing-abstract Maybe, with criterion/reason. | PASS using real screening. |
| 6 | Included paper has P/I/C/O spans with exact offsets. | PASS for span data; visual browser highlights not verified here. |
| 7 | Override an exclusion, confirm then reject a pair, relabel a PICO span; inspect all four audit entries and effective results. | PASS through API. |
| 8 | Rerun twice; retain audit rows, human label, edited PICO and rejected-pair visibility. | PASS. |
| 9 | Export visible effective Includes; verify one UTF-8 BOM, matching PMIDs and lossless quoted/newline abstract round trip. | PASS for CSV serialization; opening in Excel not verified. |
| 10 | Check monotonic record counts after every API call and eleven persisted records at completion. | PASS. |

No automated acceptance step failed. A full interactive browser acceptance run, opening the CSV in Excel, a new live PubMed run and deployed PostgreSQL behaviour were **not verified in this task**. API success must not be reported as completion of those manual checks.

## Commands

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini -q
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/tests/test_acceptance.py -q -s
```

From `frontend/`:

```powershell
npm.cmd test
npm.cmd run build
```

On the next normal app startup, existing review databases gain only missing criteria rows. Reviewer-disabled criteria remain disabled. Rerun the selected query's pipeline to generate corrected machine results; old machine rows and human decisions remain stored.
