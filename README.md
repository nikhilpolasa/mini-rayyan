# Mini-Rayyan

A literature-review workspace: search PubMed, approve and fetch abstracts,
deduplicate, screen, tag PICO, and review every machine decision. Evidence and
human decisions remain stored; duplicates are hidden rather than deleted.

The backend and frontend are implemented. Screening, title matching, PICO rules
and CSV serialization now have baseline implementations. These are reviewer aids,
not trained clinical models or a claim of validated medical performance.

## Requirements

- Python 3.11+; the current environment uses Python 3.13.
- Node.js 22.18+ for the frontend's native Vite configuration loading.
- A contact email for live NCBI requests. An NCBI API key is optional.

## Backend setup (Windows PowerShell)

Search-thread Phase A separates query histories only. Labels, notes, human PICO
edits, duplicate groups/visibility and criteria remain shared across threads.
Phase B judgment isolation is not implemented.

Run from the repository root (`mini-rayyan/`):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the root `.env` before using live PubMed. Use your own contact email:

```dotenv
DATABASE_URL=sqlite:///./miniryan.db
NCBI_TOOL=mini-rayyan
NCBI_EMAIL=your.email@example.com
NCBI_API_KEY=
FETCH_CAP=25
SOURCE_MODE=live
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

Start with a small fetch cap for verification; the normal default is 500.
Credentials stay in `.env`, which Git ignores. The PubMed base URL is already
configured in the client; no additional API URL or PubMed login is needed.

Initialize an **empty** database once, then start the backend:

```powershell
.\.venv\Scripts\python.exe scripts/reset_db.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

For an existing database, stop the backend and run the additive migration first
from the same repository directory and with the same `DATABASE_URL`:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_add_projects.py
```

It prints the tables/legacy projects added and the backup path. Existing SQLite
files are backed up under adjacent `backups/` using SQLite's backup API (including
WAL data) before writes. Existing PostgreSQL requires `pg_dump` on PATH and a
successful backup. Failure stops the migration. Repeating it is a no-op; old
query IDs, versions, parents, records and decisions are unchanged. Startup also
uses the same backup-before-write path, but the explicit command makes the report
and backup easy to inspect. PostgreSQL integration must be tested on the target
server before deployment; SQL-generation/backup unit tests are not that proof.

The sidebar's **New search** creates a titled thread beginning at v1. **Revise
(new version)** adds a version inside the selected thread. Legacy history remains
in project 1, **Imported history (legacy)**. The URL carries `project_id` per tab;
changing threads clears query selection and resets the query form. No database
reset, automatic topic conversion or legacy history renumbering is performed.

Open `http://localhost:8000/docs` for the interactive API and
`http://localhost:8000/api/health` for liveness. Always launch database scripts and
Uvicorn from the same directory: relative SQLite URLs resolve against the working
directory. `reset_db.py` refuses populated databases and never erases data. Use
an absolute URL or a new database path to start a separate review.

Optional synthetic demo seed, only into an empty database:

```powershell
.\.venv\Scripts\python.exe scripts/seed_demo.py
```

The seed contains 3 queries, 10 fictional records, a duplicate pair and human
decisions. It is not real PubMed evidence. Live fetching stores actual source
records separately by unique PMID. Hosted PostgreSQL needs an appropriate driver
and should replace SQLite for deployment on an ephemeral filesystem.

On macOS/Linux use `.venv/bin/python`; the module commands are otherwise the same.

## Frontend setup

In another terminal, from the repository root:

```powershell
cd frontend
npm ci
```

Create `frontend/.env.local` with the backend origin, without `/api`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Then run:

```powershell
npm run dev
```

Open the printed Vite URL, normally `http://127.0.0.1:5173`. The exact origin must
be allowed by backend `CORS_ORIGINS`. Restart Vite after changing its environment.
If `VITE_API_BASE_URL` is unset, the frontend uses a browser-local mock built from
`docs/api-examples.json`. Mock counts/records are fictional and do not verify NCBI
access. Backend errors do not silently switch a live workspace to mock data.

Pages cover queries, records with label/version/visibility filters and paging,
record detail/PICO annotations, duplicates, criteria, CSV export and the decision
log. Abstracts render as escaped React text; PICO offsets are Unicode code points.
See [frontend/README.md](frontend/README.md) for frontend-specific details.

## Tests and evaluation

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini -q
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/tests/test_screening.py backend/tests/test_pico_matching_export.py -q
.\.venv\Scripts\python.exe fixtures/evaluate_screening.py
```

From `frontend/`:

```powershell
npm test
npm run build
```

Unit tests block live HTTP, use temporary databases, check exact PICO offsets,
matching thresholds/conference safety, CSV round trips, rerun stability and human
history preservation. The fixtures contain 80 synthetic screening cases and 10
synthetic duplicate pairs. Screening agreement is 77/80 synthetic reference
outcomes, with three documented keyword-context false positives; this does not
measure real PubMed accuracy. Independently label actual fetched abstracts using
`fixtures/pubmed_screening.template.json` before reporting real-data metrics.

The current algorithm versions are `screen-v3`, `pico-v2` and `dedup-v3`.
This advances past the original stubs, so rerunning processes old cached results
under new versions while preserving their history and all human decisions. The
shared matching thresholds are imported by the grouping service. Future algorithm
changes must advance the corresponding version constants again.

A saved human Include triggers record-only PICO tagging in a separate transaction,
without a full pipeline run. A tagging failure is logged and leaves the reviewer
decision committed. Record detail and CSV export accept optional `query_id` to
select that query's machine context; omitting it keeps the latest-context view.

Manual live check (requires configured `NCBI_EMAIL` and network access):

```powershell
.\.venv\Scripts\python.exe backend/tests/manual_pubmed_smoke.py --query 'sertraline[tiab] AND placebo[tiab]'
```

It performs a count search, a one-ID search and a single EFetch batch. Successful
completion verifies access/parsing, not clinical validity. A live fetch remains a
required checkpoint demonstration; do not substitute mock results for it.

## Five-minute demo and Checkpoint 1

1. State the review question and criteria from [Step 0](docs/step0.md).
2. Save v1 and then v2 using the query examples there. Show actual hit counts and
   PubMed translations; inspect v1 to demonstrate unchanged query content.
3. Approve each version, pull a small set, and poll query/run status. Show an
   overlapping PMID stored once and linked to both versions. This completes the
   live search/approval/fetch/database portion of Checkpoint 1.
4. Run the pipeline. Inspect Include/Exclude/Maybe and reasons, the duplicate
   queue, and PICO annotations. PubMed often has no duplicate pair; use the clearly
   identified synthetic fixture/seed for that demonstration instead of claiming a
   real duplicate was found.
5. Override a label, confirm/reject a pair and edit a PICO span. Add a note. Rerun:
   show that records and human decisions remain. Toggle a criterion, rerun and
   inspect the new machine version. Demonstrate undo as another audit entry.
6. Download effective visible Includes as CSV, inspect the decision log, and
   explain the two query-change cases in the [one-page loop design](docs/loop-design.md).

Checkpoint 1 requires the written question/criteria, one-page loop design,
database design and a successful small **live** run of steps 1-3. The code and
protocol documents alone do not establish that the live demonstration passed.
The 60-100 independently reviewed PubMed abstracts are later validation work.

## Rule methods and limits

| Criterion | Metadata field used | Fallback algorithm | Known failure cases |
|---|---|---|---|
| Non-human | MeSH `Animals` without `Humans` | Animal/in-vitro title or abstract terms | Background/negated animal mention; mixed Animals+Humans is retained |
| Non-English | Scalar `language` | Deterministic language detection | Short, mixed or non-Latin text; secondary language may be lost |
| Case report | `pub_types` | Case-report title regex | Missing type and title phrase; contextual false positives |
| Simulation | None | In-silico/Monte Carlo/model keywords | Background mention or unlisted synonym |
| No abstract | Empty `abstract` | None; Maybe | No text to assess |
| Query relevance | None | Query-group term matching | Synonyms and negation |

Each screen reason ends with its evidence source. Run
`python scripts/screening_report.py` for per-criterion source counts on the
clearly synthetic fixtures; those counts are not clinical accuracy estimates.

- **Screening:** MeSH species tags, language metadata and publication types first;
  animal/title regexes and deterministic language detection as fallbacks.
  Simulation is a keyword algorithm. Active exclusions precede Maybe. Missing
  abstracts, missing concepts or uncertain language remain Maybe. Any criterion
  toggle is logged; relevance terms come from the query, never a hardcoded topic.
- **Matching:** normalize Unicode/case/punctuation/whitespace; exact normalized
  PMID or DOI gives 1.0. Distinct known DOIs stay separate. Otherwise RapidFuzz
  title ratio supplies a [0,1] score. Auto is >=0.95 with first-author agreement,
  publication years within one, and no conference/journal/page conflict.
  Scores [0.85,0.95) require review; lower scores are nonmatches. Unsafe high title
  similarities are capped just below the auto threshold. Strong shared identifiers
  identify the same paper even if descriptive metadata differs. Collective names
  are compared in full. Threshold constants live in `matching.py`; the core
  grouping service imports these same cutoffs.
- **PICO:** generic population/intervention cues and active query terms; comparator
  and outcome phrases. Tags index the original stored text, not a normalized copy.
  Uncontextualized query terms are tentative intervention candidates. Overlapping
  labels and ambiguous phrases require human review; this baseline is not a trained
  biomedical tagger.
- **CSV:** the service uses `csv.DictWriter`, stable fields and a UTF-8 BOM. Its
  contract returns `str`; encode with `utf-8` because the BOM is already present.
  Callers select Included rows. The API already exports visible effective Includes
  with an Excel-friendly BOM and correctly quoted commas/newlines.

The in-process background queue uses independent sessions, a local lock and
per-step transactions. Run one backend worker; jobs are not durable across process
crashes. `SOURCE_MODE=snapshot` with `SNAPSHOT_PATH` selects the
[provisional offline format](docs/snapshot-format.md); it is not the organizer's
announced format. Exact revert, diff views and durable recovery
remain Level 2 work. Never delete evidence to recover or retry a review.

PubMed content is provided through NCBI/NLM. Inclusion does not imply endorsement;
abstracts may be copyrighted and should not be redistributed without permission.
The frontend links the official [NCBI disclaimer](https://www.ncbi.nlm.nih.gov/home/about/policies/).
