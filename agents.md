# AGENTS.md: Mini-Rayyan

Instructions for Codex CLI and any other coding agent working in this repo. Read this file fully before changing anything. The full requirements are in `docs/PRD.md`; requirement IDs below (Q1, F2, DD3 ...) refer to it.

## 1. What this project is

Mini-Rayyan is a small version of Rayyan.ai, built for a 72-hour hackathon. A researcher searches PubMed from inside the tool, approves searches, and pulls abstracts. The tool deduplicates, screens (Include, Exclude, Maybe with a reason) and tags PICO (Population, Intervention, Comparator, Outcome). A human can override duplicates, exclusions and PICO tags, and every change is logged.

**Priority order:** (1) a working end-to-end run, (2) human control and logging, (3) clean design for the query-change loop, (4) polish. A simple method that runs beats a clever one that does not. Do not add features nobody asked for.

## 2. Golden rules (never break these)

1. **Never delete data.** No `DELETE` on `records`, ever. Duplicates and excluded records are hidden with status flags and can be restored.
2. **Machine results and human decisions live in separate tables.** Reruns write only to machine tables (`screen_results`, `pico_spans` with `source='machine'`, `dup_groups`, `group_members`). Human actions go to `decisions`, which is **append-only** (never UPDATE or DELETE rows there).
3. **Effective status = latest human decision, else the machine result** of the selected rule set version.
4. **Every machine output row stores the version that produced it:** `rule_set_version` (`screen-v1`, `pico-v1`, `dedup-v1`) and the query or run id. A new version writes new rows; it never edits old ones.
5. **Query versions are immutable.** Editing a query creates v(n+1) with `parent_id`. A saved version is never modified.
6. **Stay in your own folder** (section 4). Do not change function signatures or API shapes from section 7 without asking the maintainer (Karthikeya).
7. **Never commit secrets.** NCBI key and DB URL come from `.env`. Keep `.env` in `.gitignore`; provide `.env.example`.
8. **No hardcoded topics.** Judges test unseen queries. Topic words (sertraline, depression and so on) may appear only in criteria definitions, fixtures, tests and docs, never in pipeline logic. PICO terms come from the active query.
9. **Respect external rate limits** (section 8).
10. **Working beats clever.** Rules first. No LLM calls, ML models, Celery, Redis or microservices in the core pipeline unless the maintainer asks.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic |
| DB | SQLite locally; Postgres (Neon or Supabase) when deployed. Same code through `DATABASE_URL` |
| Frontend | React, Vite, TypeScript, Tailwind, TanStack Query |
| PubMed | `httpx`, `xml.etree.ElementTree` |
| Matching | `rapidfuzz` |
| NLP | `re`, optional spaCy `PhraseMatcher`, `langdetect` fallback |
| Tests | `pytest` (backend), `vitest` optional (frontend) |
| Jobs | FastAPI `BackgroundTasks` |

Environment variables (`.env`): `DATABASE_URL`, `NCBI_TOOL` (default `mini-rayyan`), `NCBI_EMAIL`, `NCBI_API_KEY` (optional), `CORS_ORIGINS`, `FETCH_CAP` (default 500), `SOURCE_MODE` (`live` default, or `snapshot`). Frontend: `VITE_API_BASE_URL`.

Commands (create these if missing):

```
# backend
cd backend && python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
pytest -q

# frontend
cd frontend && npm install && npm run dev
```

## 4. Repo layout and ownership

```
mini-rayyan/
  AGENTS.md
  .env.example
  docs/               PRD.md, api-examples.json, step0.md, loop-design.md   (Nikhil)
  scripts/            reset_db.py, seed_demo.py                              (Karthikeya)
  fixtures/           sample abstracts, synthetic duplicates, labels         (NLP teammate)
  backend/
    requirements.txt
    app/
      main.py db.py models.py schemas.py                                      (Karthikeya)
      routers/                                                                (Karthikeya)
      services/
        pubmed.py  pipeline.py  dedup.py  decisions.py                        (Karthikeya)
        screening.py                                                          (NLP teammate)
        pico.py  matching.py  export.py                                       (Nikhil)
    tests/
  frontend/                                                                   (Jeswanth)
```

If your task needs a change in a file you do not own, stop and describe the change needed instead of editing it.

## 5. Data model (summary)

Tables: `queries`, `records`, `query_records`, `dup_groups`, `group_members`, `criteria`, `screen_results`, `pico_spans`, `decisions`, `run_log`. Column details are in `docs/PRD.md` section 7.

Constraints that must exist:
- `records.pmid` UNIQUE; inserts are upserts.
- `query_records` PK (`query_id`, `record_id`): a record found by two queries is stored once.
- `queries` UNIQUE (`project_id`, `version`).
- `screen_results` UNIQUE (`record_id`, `rule_set_version`).
- All timestamps in UTC.
- Level 1 has one implicit project (`project_id = 1`); keep the column.

## 6. Pipeline behaviour

Order: **fetch, dedup, screen, PICO.** `services/pipeline.py` runs these for a query.

- **Fetch (F1 to F8):** all literature access goes through a `SourceClient` interface in `pubmed.py` (`search_count`, `search_ids`, `fetch_records`) with `live` and `snapshot` implementations chosen by `SOURCE_MODE`. The organizers test without live servers and will announce the snapshot format later, so keep the adapter thin. Approved queries only; incremental (skip stored PMIDs but still add the `query_records` link); background job with status polling; cap per search.
- **Dedup (DD1 to DD7):** exact DOI or PMID first, then fuzzy. Details in section 9. One representative per group; the others are hidden, not deleted. Rerunnable on the full stored set.
- **Screen (S1 to S5):** only non-hidden records. Rerun only for new or changed records. Never touch human decisions.
- **PICO (P1 to P5):** only Include (and optionally Maybe). Offsets against the exact stored abstract string.
- Log every run in `run_log` (query id, step, rule_set_version, status, counts, start and finish times).
- Keep the pipeline deterministic (N1): same input, same output.
- Record counts and durations per step in `run_log.counts_json` (records in, auto-excluded, groups formed, uncertain pairs, seconds taken). Human overrides go in `decisions`. The report needs these numbers (PRD section 20).

## 7. Contracts (do not change without asking)

Function contracts:

```python
# services/screening.py
def screen(record: dict, active_criteria: list[str]) -> dict:
    # {"label": "include|exclude|maybe", "reason": str, "criterion": str}
    # An "exclude" MUST have a non-empty reason and criterion key.

# services/pico.py
def tag_pico(text: str, query_terms: list[str]) -> list[dict]:
    # [{"label": "P|I|C|O", "start": int, "end": int, "text": str}]
    # text[start:end] == span["text"] must always hold.

# services/matching.py
def normalize_title(title: str) -> str: ...
def pair_score(a: dict, b: dict) -> dict:
    # {"score": float, "match_type": "exact|fuzzy|none"}

# services/export.py
def to_csv(rows: list[dict]) -> str: ...
```

`record` keys: `id, pmid, doi, title, abstract, year, journal, language, pub_types, mesh`, plus `query_groups` (list of term lists from the active query, set by the pipeline). Any of `doi, abstract, year, journal` may be `None`; functions must not crash on missing fields.

API endpoints:

```
POST /api/queries                 {text, date_from, date_to} -> {id, version, hit_count, translation}
GET  /api/queries                 GET /api/queries/{id}
POST /api/queries/{id}/approve    POST /api/queries/{id}/fetch
POST /api/pipeline/run?query_id=
GET  /api/records?query_id=&label=&show_hidden=&limit=&offset=
GET  /api/records/{id}            GET /api/runs?query_id=
GET  /api/duplicates
POST /api/decisions               {entity_type, entity_id, action, new_value, note}
GET  /api/decisions
GET  /api/criteria                PATCH /api/criteria/{key}
GET  /api/export.csv              GET /api/health
```

Example payloads live in `docs/api-examples.json`. Keep them in sync when the API changes. The frontend mocks from this file.

## 8. PubMed rules (E-utilities)

- Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils`. Use `esearch.fcgi` for IDs and counts, `efetch.fcgi` (`db=pubmed`, `retmode=xml`) for records.
- Send `tool` and `email` on every request. Add `api_key` when set.
- Limit: 3 requests/second without a key, 10 with one. Sleep at least 0.34 s between calls. Retry 429 and 5xx with exponential backoff.
- Hit count: ESearch with `retmax=0`. Show `querytranslation` in the UI (PubMed rewrites queries).
- `retmax` defaults to 20, so always set it explicitly and page with `retstart`. ESearch retrieval has a cap (around 10,000; verify in the docs), so respect `FETCH_CAP`.
- Date range: `datetype=pdat`, `mindate` and `maxdate` (both required).
- EFetch: use POST for batches of 200 IDs or fewer.
- Parsing:
  - `ArticleTitle` and `AbstractText` may contain inline tags (`<i>`, `<sup>`). Use `"".join(el.itertext())`.
  - Structured abstracts have several `AbstractText` parts; join them. Some records have no abstract.
  - DOI comes from `ArticleId[@IdType="doi"]`.
  - Year may be missing; fall back to `MedlineDate` with a regex.
  - Collective-author records may lack `LastName`.
  - Skip `PubmedBookArticle` entries.
- The UI footer shows NCBI's disclaimer. Abstracts may contain copyrighted material; do not redistribute them. Run large jobs between 9 pm and 5 am US Eastern or on weekends.

## 9. Method rules

**Dedup (`matching.py`, `dedup.py`)**
1. Same normalized DOI (lowercase, trimmed) or same PMID gives score 1.0 and auto-group.
2. No DOI: compare cleaned title (lowercase, punctuation removed, whitespace collapsed) with `rapidfuzz`, plus year (difference 1 or less), first-author last name, and journal or pages as tie-breakers.
3. Score 0.95 or more with matching year and author: auto-group. Score 0.85 to 0.95: uncertain pair for human review. Below 0.85: no match.
4. A journal paper and its conference version are not duplicates. If titles match but publication type or journal suggests a conference version, or years differ by more than 1, do not auto-merge.
5. Thresholds are constants in one place so they can be tuned and reported.

**Screening (`screening.py`)**
- `non_human`: MeSH has "Animals" without "Humans". Fallback keywords: rat, rats, mice, mouse, murine, in vitro, zebrafish. New records may lack MeSH, so the fallback matters.
- `non_english`: `language` field is not `eng`. Fallback: `langdetect` on the abstract when the field is missing.
- `case_report`: publication type "Case Reports", or title regex such as `\bcase report\b`.
- `simulation`: keywords such as "in silico", "Monte Carlo", "simulation model", "computational model".
- `no_abstract`: label Maybe, reason "no abstract".
- **Include vs Maybe (S6):** if no exclusion matches, use `record["query_groups"]` (the active query split on top-level AND). Every group has a term in title or abstract: Include, reason "matches all query concepts". Only some groups match: Maybe, reason names the missing group. Never use hardcoded topic words for this.
- Respect `active_criteria`. Return the first matching exclusion's reason and criterion key. Explain the reason in plain words ("MeSH Animals without Humans").
- Report in the README which criteria use metadata and which use an algorithm.

**PICO (`pico.py`)**
- Intervention and Population: terms from `query_terms` plus patterns (for example "patients with", "adults with").
- Comparator (own rules): "placebo", "versus", "vs.", "compared with", "usual care", "control group", "waitlist".
- Outcome: "primary outcome", "change in", "reduction in", "score", "mean difference".
- Spans must not crash on empty text. Offsets index the exact string stored in the database; do not normalize before computing them.

## 10. Versioning (so v2 never breaks v1)

**Git**
- `main` always runs. No direct commits to `main`.
- Branches: `feat/core`, `feat/frontend`, `feat/screening`, `feat/pico`. The maintainer merges into `dev`, tests, then merges to `main`.
- When the end-to-end run passes, tag `v1.0`. Deploy from the tag. Later work goes on `v2-work`; tag `v2.0` only when it works. If v2 fails, `git checkout v1.0`.

**Pipeline**
- Rule sets carry labels (`screen-v1`, `pico-v1`, `dedup-v1`) stored with every result. A new rule set writes new rows. Old rows stay untouched.
- Query versions v1, v2, v3 are separate rows. Reverting means reading the old version again; nothing is overwritten.

## 11. Level 2 readiness (design now, implement later)

Level 1 must not block these (see PRD section 11):
- Store which query version found each record (`query_records`).
- Decisions belong to the group, not the query.
- An excluded record found again keeps its status and gains only a new `query_records` link.
- Two records judged differently that become duplicates mark the group as **conflict** for the reviewer; never choose silently.
- Diff view, exact revert and run log are bonus items. Do not build them until Level 1 is tagged `v1.0`.

## 12. Testing and definition of done

Every function or endpoint you add needs tests. Run them before you finish and report the result.

- `screening.py`: 5+ cases per criterion, including records with missing fields. Score on `fixtures/` labels.
- `matching.py`: exact DOI match, fuzzy match, a pair that must not merge (conference version), missing-DOI cases.
- `pico.py`: `text[start:end]` equals span text for every span; handles empty text.
- `export.py`: commas, quotes and newlines survive a round trip.
- `pubmed.py`: parser tests on saved XML fixtures (no network in unit tests); one manual smoke test against the live API.
- Pipeline: running twice gives the same result; human decisions survive a rerun; `COUNT(*)` of `records` never decreases.

A task is done when: tests pass, no files outside your folder changed, contracts unchanged, no secrets in the diff, and you summarized what changed and how you tested it.

## 13. Code style and working habits

- Python: type hints, small functions, docstrings stating inputs and outputs. Format with `ruff` or `black`. Use `logging`, not `print`.
- TypeScript: strict mode; keep components small; API calls in one `api.ts`.
- Handle `None` and missing fields everywhere; never assume a DOI, abstract or year.
- Commit small, with messages like `feat(screening): add non_human rule (S1)`.
- Prefer boring, readable code over clever code.
- If a requirement is unclear, ask; do not invent behavior. If you hit a bug caused by someone else's module, describe it instead of patching their file.

## 14. Role-specific instructions

### Karthikeya: core backend and integration
Build the repo scaffold, models, `pubmed.py`, query-version logic, routers, `dedup.py` (grouping from `pair_score` results), `decisions.py`, `pipeline.py`, effective-status logic, `run_log`, CORS, deploy. Use stub versions of `screen`, `tag_pico` and `pair_score` until the real ones land. Merge branches into `dev`, run the acceptance test in PRD section 15, then tag `v1.0`.

### Jeswanth: frontend
Build Query, Records, Record detail (abstract with colored PICO highlights, override buttons, notes), Duplicates (confirm or reject pairs), Criteria (toggles), Export. Develop against a mock built from `docs/api-examples.json`, then switch `VITE_API_BASE_URL`. Show hit count, `querytranslation`, fetch progress and the NCBI disclaimer. Show the reason and source (machine or human) next to every label. Escape HTML before highlighting.

### NLP teammate: screening
Implement `screen()` per section 9 and 7. Build `fixtures/` with 60 to 100 real PubMed abstracts and hand labels, plus synthetic duplicate pairs for dedup tests. Write a script that scores the rules on the fixtures (precision and recall per criterion). Keep each rule independent so the reviewer can toggle it.

### Nikhil: PICO, matching and docs
Implement `pico.py`, `matching.py` and `export.py` per sections 9 and 7, with tests. Write `docs/step0.md` (review question and criteria table), `docs/loop-design.md` (one page, from PRD section 11), the README (setup, run, test, demo steps), and the report outline (three pages at most, with estimates labeled and assumptions listed).

## 15. When to stop and ask the maintainer

- A contract (function signature, API shape, table column) needs to change.
- You need a file outside your folder.
- A rule conflicts with the PRD.
- A task would add an ML model, an LLM call or a new service.
- You are about to delete data or overwrite machine or human results.

## 16. Quick-start prompt template

```
I own <your folder/files> in Mini-Rayyan. Read AGENTS.md and docs/PRD.md.
Implement <task> per the contracts in AGENTS.md section 7.
Use fixtures in /fixtures. Write tests, run them, and do not edit files outside my folder.
When finished, summarize the changes and the test results.
```