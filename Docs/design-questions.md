# Mini-Rayyan: Design Questions for Codex

Put this file at `docs/design-questions.md`.

## Instructions for Codex (read first)

Read `AGENTS.md` and `docs/PRD.md`. Then answer every question below. **Do not write application code in this task.**

For each question:
1. Propose a concrete answer. Prefer the simplest approach that works end to end.
2. Give a one-line reason.
3. List which PRD requirement IDs it affects (Q1, F2, DD3 ...).
4. Say whether it changes a contract (function signature, API shape, table column). If yes, flag it **CONTRACT CHANGE**.
5. Mark it **DECIDED** (safe default, team can proceed) or **OPEN** (needs a human vote).
6. If an answer conflicts with the PRD or AGENTS.md, say so and propose the fix.

Write the result to `docs/design-decisions.md` as one table per section with columns: `ID | Question | Answer | Reason | Affects | Status`.
At the end, add: (a) a list of every OPEN item, (b) a list of every CONTRACT CHANGE, (c) the 5 riskiest assumptions in the design.

---

## A. Team and logistics
- A1. Who owns which folder, and what happens when two people need the same file?
- A2. How often do branches merge into `dev`, and who runs the end-to-end test after each merge?
- A3. Which time zone are deadlines in, and when exactly are hours 12, 36, 60 and 72?
- A4. Where do we ask the organizers about the snapshot format, judge access and submission?
- A5. Is a team of four UG3 students allowed under the mixed-years rule?

## B. Review topic and criteria (Step 0)
- B1. Is the demo topic fixed (sertraline for MDD), and how do we prove the code is not tied to it?
- B2. Which three other topics will we smoke-test with to simulate the judges' unseen queries?
- B3. For each exclusion criterion, which part comes from metadata and which from our own algorithm?
- B4. Which extra exclusion criteria come from our own literature search, and why?
- B5. What does the reviewer see when a criterion is switched off, and what gets rescreened?
- B6. Can the reviewer add a custom criterion in the UI, or is that out of scope?

## C. Query and query versions (Step 1)
- C1. Is query text stored as a raw PubMed string, as structured groups with operators, or both?
- C2. How do we derive `query_groups` (concept groups for Include vs Maybe) from the query? What about OR inside a group, NOT terms, and field tags?
- C3. Does the Query form let the researcher label each concept group as P, I, C or O, and does `tag_pico` use that?
- C4. How do we show PubMed syntax errors and warnings (ESearch error and warning lists) to the user?
- C5. What happens when the hit count is 0, or is above `FETCH_CAP`? Which records are kept: top N by relevance or by date, and does the sort order stay fixed so results repeat?
- C6. Is the date filter on publication date or entry date, and is it inclusive?
- C7. Can two query versions have identical text? Do we warn or reuse?
- C8. What does "approve" mean? Is it per version, can it be undone, and can an approved version still be cloned?
- C9. What if a query is edited or a new version created while a fetch is running?

## D. Fetch (Step 2)
- D1. If a fetch fails halfway, do we resume or restart? Which status values exist (saved, approved, fetching, fetched, failed, partial)?
- D2. How do we detect that PubMed changed a record since we stored it (corrected abstract, retraction)? Do we refetch, and when?
- D3. How do we define "new or changed" for later steps: a content hash of title plus abstract?
- D4. Who registers the NCBI tool name and email, and where does the API key live in dev and in the deployed demo?
- D5. How do we respect the "large jobs on weekends or 9 pm to 5 am US Eastern" guidance in a demo?
- D6. How does snapshot mode pick records for a query it never saw, and what does it return when nothing matches?
- D7. What do we do when PubMed is down during the demo?

## E. Database
- E1. Primary key: internal id or PMID? What about future sources (Europe PMC) with no PMID: composite unique on (`source`, `source_id`)?
- E2. Authors, MeSH and publication types: JSON columns or normalized tables?
- E3. Where is "effective status" computed: SQL view, service function, or a cached column? How is it kept correct?
- E4. How do we enforce append-only `decisions` (code convention only, or a DB trigger)?
- E5. Which indexes are needed for the list, detail and dedup queries?
- E6. How do we keep SQLite (local) and Postgres (deployed) behaving the same, and how do we reset schema changes during development?
- E7. Do `project_id` columns stay unused in Level 1, and how do we make sure nothing breaks when they are used?
- E8. How do we store the raw API response for each record, if at all, and is it worth the size?

## F. Deduplication (Step 4)
- F1. How will we identify "the same paper" with no DOI? Which fields do we compare, and what threshold? (original question)
- F2. Which record becomes the group representative (most complete, has DOI, lowest id)? Can a human change it?
- F3. If A matches B and B matches C but A does not match C, how do we group (union-find, or only direct matches)?
- F4. While a pair is uncertain, is either record hidden? What does the UI show?
- F5. When a human rejects a pair, how do we remember it so reruns do not propose it again?
- F6. How do we avoid comparing every pair (blocking by year, first-author initial or title prefix)? What is the expected cost at 5,000 records?
- F7. How do we separate errata, comments, replies and corrections from true duplicates?
- F8. What exactly counts as a "further report of one study" in code (conference version, preprint)? How do we detect it from metadata?
- F9. Is dedup computed within a query version, across all versions, or both? Which set is "combined"?
- F10. How do we build realistic test duplicates when PubMed alone rarely produces them?

## G. Screening (Step 5)
- G1. When several exclusion criteria match, do we store the first match or all of them? Which does the UI show?
- G2. What is the criterion precedence order, and is it configurable?
- G3. How are records with both Animals and Humans MeSH terms treated?
- G4. How do we treat a record whose `language` is missing, or has several languages?
- G5. How do we treat age: is "adults only" an exclusion, or a Maybe, when only children appear in the MeSH age groups?
- G6. What is the exact rule for Include versus Maybe, and how do OR groups and NOT terms change it?
- G7. Do hidden duplicates get screening results? Does the group inherit the representative's result?
- G8. When `rule_set_version` changes, do old human overrides still apply? On which entity (record or group)?
- G9. What is the reason format (a code plus plain text) so the UI can group and the report can count?
- G10. How do we measure screening quality on the fixtures, and what precision and recall would make us keep a rule?

## H. PICO tagging (Step 6)
- H1. Which records get PICO: Include only, or Maybe too? What if a human changes Maybe to Include later?
- H2. Is tagging computed once and stored, or computed on demand?
- H3. May spans overlap, and may one word carry two labels? Which label wins?
- H4. How do we use structured-abstract section labels (Methods, Results) as hints?
- H5. Which Comparator patterns do we include, and how do we avoid tagging a comparator word in the Background section?
- H6. How are human edits stored: add span, remove span, relabel? How do offsets stay valid?
- H7. How do we handle abstracts with special characters, HTML entities or non-Latin text?
- H8. What is the evaluation: how many abstracts do we hand-tag, and by whom?
- H9. What would trigger moving from rules to a trained tagger?

## I. Human overrides and logging
- I1. Where does a human override a decision, and how is each change logged? (original question)
- I2. How will the schema store machine results and human decisions separately? (original question)
- I3. Without login, how do we fill `actor`? A name field in the UI, or a fixed reviewer name?
- I4. Is "undo" a new decision that restores the old value? How does the UI show the history?
- I5. Where are notes stored, and can a note exist without a label change?
- I6. Are bulk actions needed (exclude all of a criterion, confirm all pairs above a score)? Are they logged per record?
- I7. Does overriding a duplicate decision trigger rescreening, or just flag the group as changed?

## J. Review screen and export (Step 7)
- J1. What are the default sort order and page size for the result list?
- J2. Which columns go into the CSV: PMID, DOI, title, year, journal, abstract, label, reason, source of decision, PICO text, notes, query versions that found it?
- J3. Does export include only the group representative, and what if a human overrode which record is shown?
- J4. How do we show hidden duplicates and excluded records without cluttering the list?
- J5. What does the UI show while a fetch or pipeline run is in progress, and when it fails?

## K. Level 2 loop (design required, implementation bonus)
- K1. What happens when a record you excluded appears again under a new query? (original question)
- K2. What happens when two records you judged differently turn out to be duplicates? (original question)
- K3. When groups merge, which decision wins by default, and how is the conflict shown?
- K4. How do we decide "new or changed" so we re-screen and re-tag only those?
- K5. For the diff view, relative to which version do we compute records added, records removed and groups newly merged?
- K6. What does "revert to v1" mean in the data: change a current-version pointer, or rebuild the record set? How do we make group ids and results repeat exactly?
- K7. Is fetch cap or sort order a risk to repeatability? How do we freeze it?
- K8. Where is the "current query version" stored, and can two be open at once?
- K9. What must Level 1 store now so Level 2 needs no rebuild?
- K10. What goes in the run log (version, step, time, counts) and how do we use it to show what changed?

## L. Testing and evaluation
- L1. How do we pick 60 to 100 fixture abstracts without bias, and what labeling guide do we use?
- L2. Who labels, and do two people label a sample to check agreement?
- L3. Which metrics and targets do we report for dedup, screening and PICO?
- L4. How do we test with unseen queries before the judges do?
- L5. What does the end-to-end acceptance test (PRD section 15) look like as an automated script?
- L6. How do we test snapshot mode without live servers?
- L7. What is the largest record set we have tested, and what breaks first?

## M. Deployment and demo
- M1. Where do the frontend, backend and database run, and what environment variables does each need?
- M2. How do we handle cold starts on a free host before the demo?
- M3. How do judges reach the tool, and do they share one database? If two judges edit at once, do we need per-session projects?
- M4. How do we reset demo data between runs?
- M5. Is the demo live or recorded, and what is the backup if a live API call fails?
- M6. What is the order of the five-minute demo, and which screens does each speaker present?

## N. Report and compliance
- N1. For each step, what was the simplest approach first, and why did we keep or replace it?
- N2. Which figures do we report as estimates, and what assumptions (for example seconds per abstract) do we list?
- N3. Is any LLM used for the product itself or only to write code and docs? How do we justify it?
- N4. How do we respect NCBI's terms (tool name, email, disclaimer, rate limits) and the licences of any datasets (SYNERGY CC0; EBM-NLP for training and testing only, no redistribution)?
- N5. Do we store or redistribute abstracts in the repo, and is that allowed?

## O. Scope (from the original list)
- O1. If time runs short at hour 36, which step do we simplify first? (original question)
- O2. Will we attempt the Level 2 loop, or only submit the design? (original question)
- O3. What is the minimum demo that still works end to end, and who decides to cut a feature?
- O4. What are the feature-freeze rules after hour 36?
- O5. Which bonus items come first if time remains: query versions that keep decisions, diff view, exact revert?