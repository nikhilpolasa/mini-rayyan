# Screening validation data

`screening_synthetic.json` contains **80 authored synthetic cases**, each with
explicit reference labels, per-criterion binary labels and a rationale. No real
PubMed abstracts or PMIDs are represented. Reference labels are assigned in the
fixture, not generated from `screen()` predictions. They are not independently
human-validated. This is development coverage, not a clinical validation dataset.

Three intentionally difficult negative controls expose simple keyword limitations:
a computer mouse, a title describing excluded case reports, and negated simulation
methods. Their `baseline_limitation` fields explain the expected false positives.
The evaluator reports these disagreements; the labels have not been changed to
make the baseline look perfect.

`duplicate_pairs.json` contains **10 synthetic pairs**: DOI/PMID matches, fuzzy
title variants, uncertain pairs, conference reports, distant publication years,
unrelated studies and missing metadata. Expected decisions are reviewer guidance;
no fuzzy similarity scores are fabricated. This task does not implement matching.

## Populate real PubMed evaluation data

`pubmed_screening.template.json` is deliberately empty until you fetch records.
Copy its `case_template` into `cases` once per fetched abstract (target 60–100).
Use real source PMIDs, the exact fetched abstract text, metadata and query groups.

For every record, independently review and fill in:

- `criterion_matches`: true/false for **each** rule, even when several rules match.
  Leave a value null if it has not been reviewed; null is never treated as false.
- `expected.label` and `expected.criterion`: the effective machine outcome with
  the stated `active_criteria` order. Use an empty criterion string for ordinary
  concept matching; no abstract is Maybe with criterion `no_abstract` when active.
- `label_rationale`, `reviewer`, `reviewed_at` and source provenance.

Do not automatically copy machine predictions into reference labels. Keep raw
PubMed abstracts local unless redistribution rights permit sharing them.

From the repo root, using the installed backend environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -c backend/pytest.ini backend/tests/test_screening.py -q
.\.venv\Scripts\python.exe fixtures/evaluate_screening.py
.\.venv\Scripts\python.exe fixtures/evaluate_screening.py fixtures/pubmed_screening.template.json
.\.venv\Scripts\python.exe fixtures/evaluate_screening.py --json
```

The evaluator runs each criterion in isolation, so the first exclusion cannot mask
another rule's recall. It prints TP/FP/FN/TN, precision, recall and skipped counts.
Undefined ratios print `n/a`. A wholly unreviewed template exits with code 2 rather
than presenting fake scores. Overall label/criterion agreement uses reviewed cases.

## Rule methods and precedence

| Rule | Metadata | Fallback algorithm |
|---|---|---|
| non_human | Animals without Humans excludes; Humans takes precedence | Bounded rat/rats/mice/mouse/murine/zebrafish and in-vitro keywords when MeSH is not decisive |
| non_english | eng/en/English accepts; explicit foreign language excludes | Seeded langdetect on abstract, at least 20 alphabetic characters and 0.90 top-language confidence; uncertainty gives Maybe |
| case_report | Case Reports publication type | Case-report/case report title regex, including plurals |
| simulation | None | in-silico, Monte Carlo, simulation(s), computational model(s) keywords |
| no_abstract | Empty/missing abstract | Maybe, never an exclusion |
| relevance | Pipeline-supplied query_groups | At least one bounded term per AND group; case-insensitive phrases and trailing wildcard prefixes |

Active exclusions are checked in the caller's criterion order, before Maybe
conditions. Unknown keys are ignored. Exclude always has a reason and criterion.
No abstract always remains Maybe under PRD S6, even if the named `no_abstract`
criterion is disabled (then its criterion field is empty). Missing query groups,
unmatched groups or uncertain language also give Maybe. Unknown language is never
silently classified as non-English. MeSH does not suppress publication-type or
simulation exclusions.

Pipeline integration: `SCREEN_VERSION` is now `screen-v2`, with `pico-v2` and
`dedup-v2` for the other algorithms. Rerunning the pipeline retains old stub rows
and writes the new version's machine outputs without changing human decisions.
The obsolete stub-only smoke assertions have been replaced with missing-field
contract checks. Future algorithm changes must advance the corresponding core
version constants again before processing databases with cached results.
