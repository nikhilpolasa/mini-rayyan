# Mini-Rayyan: Product Requirements Document (PRD)

Version 1.0 · 27 Oct 2026 · Team: Karthikeya, Jeswanth, Nikhil, plus one NLP teammate
Source: Mini-Rayyan Hackathon Pre-Read (Track1_PS.pdf, 24 Oct 2026)

Put this file at `docs/PRD.md`. Requirement IDs (Q1, F2, DD3 and so on) are used in commits, tests and the report.
---
## 1. Purpose

Build, in 72 hours, a small version of Rayyan.ai that works end to end.

A researcher searches PubMed from inside the tool with different keyphrases, keyphrase combinations and date ranges. The researcher picks the searches that look useful and pulls their abstracts into the tool. The tool then:

1. removes duplicate abstracts,
2. excludes studies that do not belong (non-human, simulation, non-English, case reports),
3. extracts PICO (Population, Intervention, Comparator, Outcome) from every abstract that remains.

A person stays in charge. The reviewer can override duplicates, exclusions and PICO tags, and the tool logs every change.

**Success means:** a simple tool that runs end to end beats a clever one that does not. Working beats flashy. After the loop works, improve each step as far as time allows.

## 2. Problem statement

Systematic reviews need every relevant study to be found and screened. A search returns thousands of abstracts and a human reads each one, which takes weeks. Each step (search, dedup, screen, tag) is simple on its own. The hard part is the **loop**: when the researcher edits the query, the abstracts change, so deduplication and screening must be rerun **without losing the work a reviewer has already done**.

## 3. Scope

| Level | Status | Meaning |
|---|---|---|
| Level 1 | **Mandatory** | Working UI, database, a method for every step, human overrides with a log |
| Level 2 design | **Mandatory** (one page) | How the system handles a changed query, written before coding |
| Level 2 implementation | Bonus | Query versions that keep decisions, diff view, exact revert, incremental fetch, re-screen only new or changed, run log |

**Non-goals for Level 1:** user accounts or login, multi-user collaboration, full-text PDFs, Europe PMC (stage 2, only after Level 1 works), trained ML models (only after rule baselines work), mobile layout.

Independent in-app review workspaces are also out of scope for Level 1 (E7/CC2). Each configured database is one shared workspace. For separate reviews, use separate `DATABASE_URL` values or SQLite files with operator-managed instances/restarts; no schema change or automatic per-session routing is planned. Judges sharing one URL/database can affect each other's review state; this is a known limitation (M3). Organizer access arrangements remain OPEN.

The canonical documentation folder is `docs/` (lowercase), including this PRD and `docs/design-decisions.md`.

## 4. Users

- **Reviewer (primary):** one person running a review. Wants fewer abstracts to read, clear reasons for every machine decision, and the last word on everything.
- **Judges:** test with queries and records the team has not seen. Rules must therefore work on any topic, not only the demo topic. Demo uses the live PubMed API.

## 5. Review question (Step 0)

**Question:** In adults with major depressive disorder, does sertraline, compared with placebo or another antidepressant, reduce depression severity?

| Part | Content |
|---|---|
| Population | Adults with major depressive disorder |
| Intervention | Sertraline |
| Comparator | Placebo or another antidepressant |
| Outcome | Change in depression score (HAM-D, MADRS) |

Keyphrases: "major depressive disorder", "sertraline", "placebo", "HAM-D".

- Query v1: `("major depressive disorder"[tiab] OR "depressive disorder"[tiab]) AND sertraline[tiab] AND placebo[tiab]`, 2016 to 2026
- Query v2 (loop demo): same, with `OR escitalopram[tiab]` added to the intervention group

**Criteria (each has a one-line reason; the team may add more from its own literature search):**

| Key | Rule | Reason | Source |
|---|---|---|---|
| `human_adult_mdd` | Include human studies of adults with MDD | The question is about adults | Metadata plus keywords |
| `has_comparison` | Include studies comparing sertraline with a comparator | Only comparisons answer the question | Keyword rules |
| `non_human` | Exclude animal studies | The question is about people | MeSH "Animals" without "Humans"; keyword fallback (rat, mice, murine, in vitro) |
| `simulation` | Exclude simulation or modelling studies | They model results and do not measure patients | Own algorithm (keywords: in silico, Monte Carlo, simulation model) |
| `non_english` | Exclude non-English | The team cannot check it | PubMed `Language` field; language-detect fallback |
| `case_report` | Exclude case reports | One patient cannot show an average effect | Publication type "Case Reports"; title regex fallback |
| `no_abstract` | Maybe when abstract is empty | It cannot be screened properly | Metadata |

**Rule:** the demo topic is only an example. No code may hardcode these keywords except inside the criteria definitions; PICO terms come from the active query.

Age policy (G5): no automatic age exclusion is approved. Child-only or unclear age is Maybe for manual review. The baseline does not have a dedicated age classifier, so automatic enforcement of this policy is not claimed; the reviewer must assess age eligibility.

## 6. Functional requirements

### 6.1 Query (Step 1)

| ID | Requirement |
|---|---|
| Q1 | A form accepts keyphrases, keyphrase combinations (AND, OR, NOT) and a date range. Raw PubMed syntax with field tags such as `[tiab]` is allowed. |
| Q2 | Each search is saved as a **query version** (v1, v2, v3 ...). A saved version is never edited; editing creates a new version with a `parent_id`. |
| Q3 | On save, run ESearch with `retmax=0` to get the **hit count** and PubMed's `querytranslation`. Show both. |
| Q4 | List all versions with hit count, date range and status. An old version can be reopened (read-only) and cloned into a new version. |
| Q5 | The researcher runs several searches one at a time and chooses which to pull (approve). |

### 6.2 Fetch (Step 2)

| ID | Requirement |
|---|---|
| F1 | After approval, "Pull abstracts" fetches the records of that search. |
| F2 | Use NCBI E-utilities (ESearch for IDs, EFetch for records). Send `tool` and `email` with every call. Stay under 3 requests/second (10 with an API key). Batch EFetch with POST, 200 PMIDs or fewer per call. Retry with backoff on 429 or 5xx. |
| F3 | Store per record: PMID, DOI, title, abstract (all parts joined), authors, year, journal, language, publication types, MeSH headings, source (`pubmed`). |
| F4 | Cap records per search (default 500, configurable). Set `retmax` explicitly and page with `retstart` (ESearch default is only 20). |
| F5 | **Incremental:** a PMID already stored is not fetched again, but is still linked to the new query version. |
| F6 | Fetch runs as a background job. The UI polls a status endpoint. |
| F7 | Show NCBI's disclaimer in the UI footer. Abstracts may contain copyrighted material; do not redistribute them. |
| F8 | Put all literature access behind a small `SourceClient` interface (`search_count`, `search_ids`, `fetch_records`) with two implementations: `live` (PubMed) and `snapshot` (reads a frozen file). A `SOURCE_MODE` setting switches them. The organizers will test without live servers, but the snapshot format is announced later, so keep this adapter thin. |

### 6.3 Database (Step 3)

| ID | Requirement |
|---|---|
| D1 | Tables for queries, records, query-to-record links, duplicate groups, criteria, machine screen results, PICO spans, human decisions and run log (section 7). |
| D2 | `records.pmid` is unique; inserts are upserts. A record found twice is stored once. |
| D3 | `query_records` links every record to every query version that found it. |
| D4 | **Nothing is deleted.** Duplicates and excluded records are hidden and marked. No endpoint or code path issues `DELETE` on `records`. |
| D5 | Machine results and human decisions live in separate tables. Reruns write only to machine tables. |
| D6 | Every machine output row stores the query version or run that produced it and a `rule_set_version`. |

### 6.4 Deduplicate (Step 4)

| ID | Requirement |
|---|---|
| DD1 | Group records that are the same paper, within one search and across all searches so far. Keep one **representative** per group. Hide the others; never delete. |
| DD2 | **Exact:** same normalized DOI (lowercased, trimmed) or same PMID. Score 1.0, auto-group. |
| DD3 | **Fuzzy (no DOI):** compare cleaned title (lowercase, punctuation removed, whitespace collapsed), year (difference 1 or less), first author last name, and journal or pages as tie-breakers. Title similarity with `rapidfuzz`. Score 0.95 or more with matching year and author: auto-group. Score 0.85 to 0.95: **uncertain pair**. Below 0.85: not a match. |
| DD4 | Further reports of one study (for example a journal paper and its conference version) are **not** duplicates. When titles match but publication type or journal indicates a conference version, or the years differ by more than 1, do not auto-merge; send to the uncertain queue or leave separate. |
| DD5 | A human confirms or rejects every uncertain pair and can split or merge groups. Choices are logged. |
| DD6 | Dedup reruns on the combined set of all stored records and is safe to repeat. |
| DD7 | Note: PubMed alone rarely returns the same paper twice. Test dedup with synthetic duplicate pairs in `fixtures/`. |

Approved F7 guard: title prefixes Erratum, Correction, Comment on and Reply to, and publication types Published Erratum, Comment and Retraction of Publication, prevent fuzzy auto-merge. An otherwise fuzzy candidate is capped below the auto threshold for review; shared PMID/DOI retains exact-match precedence. Unrelated below-threshold titles are not forced into the uncertain queue.

### 6.5 Screen (Step 5)

| ID | Requirement |
|---|---|
| S1 | Apply the active criteria from section 5 and mark each record **Include, Exclude or Maybe**. |
| S2 | Every Exclude has a reason and the criterion key that caused it. |
| S3 | Use the metadata field when the record has one; otherwise use the documented fallback algorithm. The report must say which criteria used which. |
| S4 | The reviewer chooses which criteria are active and can override any exclusion. |
| S5 | Only records that are not hidden duplicates are screened. Screening runs per record, so reruns only need new or changed records. |
| S6 | **Label logic.** Any active exclusion that matches gives **Exclude** (first match, with reason). If none matches, split the active query on top-level AND into concept groups. Every group has a term in the title or abstract: **Include**. Only some groups match, or there is no abstract: **Maybe** (reason names the missing group). Concept groups come from the query, never from hardcoded topic words. The pipeline passes them to `screen()` as `record["query_groups"]`. |
| S7 | Optional later: TF-IDF plus logistic regression relevance score to order Maybe records, trained on SYNERGY (CC0). |

### 6.6 PICO (Step 6)

| ID | Requirement |
|---|---|
| P1 | For every Included record (Maybe optional), tag spans as Population, Intervention, Comparator or Outcome. |
| P2 | Method: keyword and pattern rules. Intervention and Population use the active query terms plus patterns. Comparator uses own rules ("versus", "compared with", "placebo", "usual care", "control"). Outcome uses patterns ("primary outcome", "change in", "score"). |
| P3 | Each span stores label, character `start`/`end` offsets against the exact stored abstract text, and the text. |
| P4 | The reviewer can add, remove or relabel spans. Edits are logged and marked `source=human`. |
| P5 | Optional later: a tagger trained on EBM-NLP (no comparator label; licence unknown, so train and test only, do not redistribute). |

Approved H1 behaviour: after a human record Include is committed, run record-only PICO immediately in a separate session/transaction. Store machine spans and run provenance normally, preserving human edits; a tagging failure must not roll back the saved decision. This does not require a full pipeline run.

### 6.7 Review and export (Step 7)

| ID | Requirement |
|---|---|
| R1 | Result list with Include, Exclude or Maybe, reason, source (machine or human) and a hidden-duplicate indicator. Filters by label and query version, and a "show hidden" toggle. |
| R2 | Record detail shows the abstract with colored PICO highlights. |
| R3 | The reviewer can change a label, add a note, and undo. |
| R4 | CSV export of included studies (`utf-8-sig`, `csv` module so commas and newlines in abstracts survive). |
| R5 | A decision log view lists every override. |

### 6.8 Human control and logging

| ID | Requirement |
|---|---|
| H1 | `decisions` is **append-only**: entity type, entity id, action, old value, new value, reason or note, actor, UTC timestamp. |
| H2 | Effective status = latest human decision, otherwise the machine result of the selected rule set version. |
| H3 | Any decision can be undone by a new decision that restores the previous value. |

## 7. Data model

| Table | Columns (main) |
|---|---|
| `queries` | id, project_id (default 1), version, parent_id, text, date_from, date_to, hit_count, query_translation, status (saved, approved, fetching, fetched, failed), created_at. UNIQUE(project_id, version). |
| `records` | id, pmid UNIQUE, doi, title, abstract, authors_json, year, journal, language, pub_types_json, mesh_json, source, fetched_at |
| `query_records` | query_id, record_id, found_at. PK(query_id, record_id) |
| `dup_groups` | id, representative_record_id, dedup_version |
| `group_members` | group_id, record_id, match_type (exact, fuzzy), score, status (auto, pending, confirmed, rejected), dedup_version |
| `criteria` | key, project_id, label, kind, description, reason, source (metadata, algorithm, both), active |
| `screen_results` | id, record_id, rule_set_version, label, reason, criterion, run_id, created_at. UNIQUE(record_id, rule_set_version) |
| `pico_spans` | id, record_id, pico_version, label, start, end, text, source (machine, human), created_at |
| `decisions` | id, entity_type (record, group, pair, pico_span, criterion), entity_id, action, old_value, new_value, note, actor, created_at |
| `run_log` | id, query_id, step, rule_set_version, status, counts_json, started_at, finished_at |

Level 1 uses one implicit project (`project_id = 1`); keep the column so Level 2 needs no rebuild. Store all timestamps in UTC.

One configured database remains one shared review workspace. Separate reviews use separate databases/files, preserving previous evidence; no E7 schema migration or project API is part of Level 1.

## 8. API contract

| Endpoint | Purpose |
|---|---|
| `POST /api/queries` `{text, date_from, date_to}` | Save as next version; returns `{id, version, hit_count, translation}` |
| `GET /api/queries` | List versions |
| `GET /api/queries/{id}` | Detail, status, counts |
| `POST /api/queries/{id}/approve` | Mark approved for pulling |
| `POST /api/queries/{id}/fetch` | Start background pull |
| `POST /api/pipeline/run?query_id=` | Dedup, then screen, then PICO |
| `GET /api/records?query_id=&label=&show_hidden=&limit=&offset=` | Paged list (default 50) with effective status |
| `GET /api/records/{id}` with optional `query_id` | One record: full abstract, PICO spans, group, decisions, query versions that found it. Select that query's machine context when supplied; omit for existing latest-context behaviour. |
| `GET /api/runs?query_id=` | Run log |
| `GET /api/duplicates` | Groups and uncertain pairs |
| `POST /api/decisions` `{entity_type, entity_id, action, new_value, note}` | Human override |
| `GET /api/decisions` | Audit log |
| `GET /api/criteria`, `PATCH /api/criteria/{key}` | List and toggle |
| `GET /api/export.csv` with optional `query_id` | Visible effective Includes for that query/context when supplied; omit for existing latest-context behaviour. Same eight CSV columns. |
| `GET /api/health` | Liveness |

Example JSON for each endpoint lives in `docs/api-examples.json`. The frontend mocks from it.

CC7 is limited to these optional query selectors and corresponding frontend links/cache keys. No `run_id` selector, current-version pointer, workspace API or table column is added. Human decisions remain authoritative within the configured database.

## 9. Module contracts

```python
# services/screening.py
def screen(record: dict, active_criteria: list[str]) -> dict:
    # {"label": "include|exclude|maybe", "reason": str, "criterion": str}

# services/pico.py
def tag_pico(text: str, query_terms: list[str]) -> list[dict]:
    # [{"label": "P|I|C|O", "start": int, "end": int, "text": str}]

# services/matching.py
def normalize_title(title: str) -> str: ...
def pair_score(a: dict, b: dict) -> dict:
    # {"score": float, "match_type": "exact|fuzzy|none"}

# services/export.py
def to_csv(rows: list[dict]) -> str: ...
```

`record` has: `id, pmid, doi, title, abstract, year, journal, language, pub_types, mesh`, plus `query_groups` (list of term lists, set by the pipeline from the active query).

## 10. Non-functional requirements

| ID | Requirement |
|---|---|
| N1 | **Deterministic:** the same records and rules give the same output on every run. |
| N2 | **Rate limits** respected on every external call. |
| N3 | **Versioning** at three levels: git tags (`v1.0`, `v2.0`), query versions, and `rule_set_version` on every machine result (`screen-v1`, `pico-v1`, `dedup-v1`). A new version never edits old rows. |
| N4 | **Traceability:** every machine result and human change can be traced to a version and time. |
| N5 | **Secrets** (NCBI API key, DB URL) come from `.env`; never committed. |
| N6 | **Deployability:** free-tier hosting; the judges must reach the running tool. Use hosted Postgres for the deployed demo because free hosts wipe local disk. |
| N7 | **Target performance (estimates):** fetch 500 records in about 1 to 2 minutes; screening 500 records in under 30 seconds. |
| N8 | **Free compute only** (free Colab, free-tier hosting). |
| N9 | `scripts/reset_db.py` and `scripts/seed_demo.py` rebuild the database and load demo data in one command (no migration tool in Level 1). |
| N10 | **Judge-ready:** public URL, no login, `/api/health`, demo data preloaded, and graceful handling of odd records (no abstract, odd characters, non-Latin text). |

## 11. Level 2 loop design (one page, required)

For each step: what a person might go back to change, what later steps it affects, and how decisions stay safe.

| Go back to | Affects | Safety rule |
|---|---|---|
| Query | Fetch, dedup, screen, PICO | New version; old kept; incremental fetch; only new records processed |
| Approved searches | Fetch onward | Unapproved results stay in the database; nothing deleted |
| Dedup group (merge or split) | Screen, review | Decisions belong to the group; conflicts are shown, not resolved silently |
| Active criteria | Screen, PICO | Rescreen writes a new `rule_set_version`; human decisions untouched |
| PICO tags | Review, export | Human spans kept; machine spans re-tagged only for new or changed records |

**Required answers:**
1. *An excluded record appears again under a new query.* It gains a `query_records` link only. Its status stays excluded and it is not re-screened. The UI can show "also found by v2".
2. *Two records judged differently turn out to be duplicates.* They are grouped; because decisions belong to the group, the group is marked **conflict** and listed for the reviewer. Nothing is silently overwritten and the final choice is logged.

**Bonus items:** diff view (records added, removed, groups newly merged), exact revert (return to v1 gives the same records and groups), run log.

Release scope: CC3 multiple-language storage, CC4 structured-section metadata, CC5 historical snapshots/exact revert and CC6 fetch manifests are deferred until after `v1.0`. Existing query history and run logs do not prove exact replay of a changing live source. CC1 remains minimal warning display after the blocker fixes, not a broader diagnostics/schema feature.

## 12. Tech stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy |
| Database | SQLite locally; Postgres (Neon or Supabase free tier) when deployed |
| Frontend | React, Vite, TypeScript, Tailwind, TanStack Query |
| PubMed | `httpx` plus `xml.etree.ElementTree` |
| Dedup | `rapidfuzz` |
| NLP | `re`, optional spaCy `PhraseMatcher`, `langdetect` fallback |
| Jobs | FastAPI `BackgroundTasks` |
| Deploy | Vercel (frontend), Render (backend) |

Avoid until Level 1 works: LLM calls in the core pipeline, Celery, microservices, ML models.

## 13. Team and ownership

| Role | Owner (swap names as needed) | Owns |
|---|---|---|
| A. Core backend and integration (~50%) | Karthikeya | Repo, contracts, database, PubMed client, query versions, API, dedup groups, decisions, pipeline, deploy |
| B. Frontend (~20%) | Jeswanth | `frontend/`: Query, Records, Record detail, Duplicates, Criteria, Export |
| C. NLP: screening (~15%) | NLP teammate | `screening.py`, criteria rules, `fixtures/`, screening tests |
| D. PICO, matching, docs (~15%) | Nikhil | `pico.py`, `matching.py`, `export.py`, Step 0 page, loop design, README |

## 14. Milestones

| When | Deliverable |
|---|---|
| Hour 12 (27 Oct, 7 pm) | Sources understood, review question and criteria written, one-page loop design, database designed, steps 1 to 3 running on a small query |
| Hour 36 | Level 1 complete: dedup, screening and PICO baselines working end to end. **Feature freeze: only bug fixes and report after this.** |
| Hour 60 | Level 2 loop attempted if time allows; report drafted |
| Hour 72 | Repo with README a stranger can rerun, report (3 pages max), 5-minute demo |

Team target: Level 1 tagged `v1.0` today.

## 15. Acceptance test (end to end)

1. Create query v1; see hit count and `querytranslation`.
2. Create query v2 (edited); both versions listed; v1 unchanged.
3. Approve both; pull abstracts; records stored once; overlapping records linked to both versions.
4. Run pipeline: duplicates grouped (exact and fuzzy), hidden but visible with "show hidden".
5. Screening labels every non-hidden record; every Exclude has a reason and criterion.
6. PICO highlights appear on included records.
7. Override an exclusion, a duplicate pair and a PICO tag; all three appear in the decision log.
8. Rerun the pipeline; human decisions are unchanged.
9. Export CSV of included studies; opens correctly in Excel.
10. Row count of `records` never decreased at any point.

## 16. Risks and known pitfalls

| Risk | Mitigation |
|---|---|
| ESearch returns 20 IDs by default | Always set `retmax`; page with `retstart` |
| ESearch has a retrieval cap (about 10,000; check docs) | Cap pulls per search |
| Titles and abstracts contain inline tags like `<i>` | Use `itertext()` |
| Structured abstracts have several parts; some records have none | Join parts; empty abstract goes to Maybe |
| Missing DOI, year or authors | Treat as optional; parse year from `MedlineDate` with a regex |
| PubMed rewrites queries | Use `[tiab]`; show `querytranslation` |
| New records lack MeSH tags | Keyword fallback |
| 429 rate-limit errors | Sleep 0.34 s, API key, backoff |
| Free hosts wipe disk | Hosted Postgres for the demo |
| CORS errors | Configure `CORSMiddleware` early |
| Long fetch times out | Background job with polling |
| Re-fetch duplicates rows | Unique `pmid` and upsert |
| Rerun overwrites human work | Reruns write to machine tables only |
| PICO highlights misaligned | Offsets against the stored string; escape HTML |
| CSV breaks in Excel | `csv` module, `utf-8-sig` |
| Secrets leak | `.env` and `.gitignore` from the first commit |
| Hardcoded topic fails on unseen queries | Topic words only inside criteria and query terms |

## 17. Deliverables

1. Code repository with a README that lets a stranger rerun the work.
2. Report, 3 pages at most, answering: *What was the simplest approach tried first, and why was it kept or replaced? Was each added step worth the effort and compute, set against the reviewer time it saves?* Label every figure as an estimate and list assumptions. Also document the problem, the loops between steps, design choices, which exclusion criteria were used and why, whether each came from metadata or an own algorithm, and where a human decides.
3. One-page loop design (section 11).
4. Five-minute demo using the live APIs.

## 18. Open items (to be announced by organizers)

- How the frozen snapshot of results (for testing without live servers) is delivered, and its format.
- How judges reach the running tool.
- Where and how to submit; whether the demo is live or recorded.

- The separate **Scoring Metrics** document has not been read yet. Check this PRD against it, especially the Level 2 tests, before hour 36.

## 20. Evidence to collect for the report

The report must justify each step against reviewer time saved. Collect these as you build (label every figure as an estimate and list assumptions):

- `docs/experiment-log.md`: the simplest approach tried first for each step, what replaced it, and why.
- Screening: precision and recall per criterion on the hand-labelled `fixtures/`.
- Dedup: pairs found, auto versus uncertain, and how many a human confirmed or rejected.
- PICO: span agreement on about 20 hand-tagged abstracts.
- Cost: seconds per step, from `run_log`.
- Reviewer time saved (estimate): records auto-excluded or auto-hidden times an assumed seconds-per-abstract (state the assumption, for example 30 s).
- Override rate per step (from `decisions`): a rough measure of how often the machine was wrong.

## 21. Demo plan (5 minutes)

This plan matches design-decisions M6. Timings are an allocation, not a claim of a completed rehearsal.

| Order | Speaker | Screen or explanation | Seconds |
|---|---|---|---:|
| 1 | Karthikeya | Topic and Step 0 question/criteria | 20 |
| 2 | Jeswanth | Query v1/v2, hit counts and PubMed translation | 40 |
| 3 | Karthikeya | Approve, pull and demonstrate persistence | 35 |
| 4 | NLP teammate | Duplicate groups and uncertain-pair confirmation | 35 |
| 5 | NLP teammate | Screening reasons, criterion toggle and exclusion override | 45 |
| 6 | Nikhil | PICO highlights and one correction | 40 |
| 7 | Jeswanth | Decision log and CSV export | 25 |
| 8 | Karthikeya | Loop design and the two required cases | 40 |
| 9 | Team | Contingency reserve | 20 |
| Total | | Five minutes including reserve | 300 |

Record a backup video in case a live API call fails during the demo.

## 19. Definition of done (Level 1)

- All requirements in 6.1 to 6.8 pass the acceptance test in section 15.
- Tests pass for screening, matching, PICO, export and the pipeline.
- `main` is tagged `v1.0` and the deployed demo runs from that tag.
- README, Step 0 page and loop design are in the repo.
