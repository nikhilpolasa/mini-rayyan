# Query-change loop: one-page design

Based on PRD section 11. **Keep evidence and reviewer decisions; version machine
outputs.** Level 1 uses one implicit project. Content/date edits create a new
immutable query row with a parent; approval/fetch status may advance separately.

| Researcher changes | Downstream effects | Preservation rule |
|---|---|---|
| Query text or dates | Search count, fetch, dedup, screen, PICO | New query version. Fetch only unseen PMIDs; link existing records to the new version. Preserve original records and old versions. |
| Which searches are approved | Fetch and subsequent processing | Fetch only approved searches. Previously fetched evidence stays stored and traceable to its originating queries. |
| Duplicate pair/group | Visibility, screening, review | Append a confirmation/rejection/split decision. Recompute effective groups; never delete member records. Preserve member-specific disagreements. |
| Active screening criteria | Screen and PICO | Log toggles. A changed rule configuration gets a new version; machine outputs append, human work remains. |
| PICO tags or final labels | Review and export | Append human decisions/spans. Undo appends the prior value. Machine reruns never overwrite human rows. |

## Required cases

**An excluded record appears in a later query.** Its unique PMID identifies the
existing record. Add only a `query_records` link; do not fetch or duplicate it.
Its human decision still wins, and its existing machine screen result is reused
for the same rule set. The detail view shows both query versions. A deliberate
rule-set change may append a new machine result without removing the exclusion
history or overriding a human exclusion.

**Differently judged records are discovered to be duplicates.** Preserve both
records and both decisions. Project a conflicted group, keep its records visible,
and queue it for the reviewer; never silently select one judgment. In the current
API, conflicted members have `pending` status. A new group-level label resolves
the disagreement with an audit trail. Pair IDs use stable record IDs, not query
IDs, so decisions survive new searches.

## Runs, versions and recovery

Process in order: fetch → dedup → screen → PICO. Record query/run provenance,
algorithm/configuration version, status, counts and elapsed seconds. Reuse
unchanged machine results; retain old versions when rules change. Effective
labels use the latest applicable human decision, otherwise the selected completed
machine version. Export visible effective Includes only.

Current jobs use independent sessions and per-step transactions. A failed step
rolls back its outputs and retains a failed run; completed earlier steps remain.
The in-process queue does not survive restart; use one worker and inspect/recover
interrupted jobs before retrying. Increment algorithm versions when replacing
cached stubs; otherwise old outputs may be reused incorrectly.

## Stored-data diff and as-of view

A query version's record set is exactly the records linked to it in
`query_records`. Existing link rows are immutable and records are never
deleted, so the stored set can be recomputed. A later pull of the same query
can append links, so the set is stable only after fetching is finished. Groups
"as of" a version are recomputed from that
set with the current deterministic matching thresholds and guards, and human
pair decisions only when both members are inside the set. This is a read-only
projection; each group ID is its lowest record ID (the representative).
`GET /api/queries/{id}/as-of` returns IDs, groups, hidden members, effective
labels and a SHA-256 hash of sorted record IDs and group structure.
`GET /api/queries/{id}/diff?base={other_id}` compares linked sets and reports
added/removed/common records and newly merged groups. The default base is the
query parent. An empty diff has no additions, removals or merges.

**Limit:** exact revert means the same stored record set and recomputed groups
under the same matching rules and pair decisions. A later pair decision or
rule change can change a prior version's projected groups; labels can change
after human decisions. Fresh live searches can return different IDs later, so
this is not a frozen-source replay. Durable job recovery and incremental
processing of externally updated abstracts remain future Level 2 work.

## Implemented loop checks

The combined dedup projection connects a new paper to two earlier groups using
the existing DOI/title/year/author matching rules. It keeps one lowest-ID
representative and all stored records. Different human Include/Exclude labels
leave all conflicted members visible with `pending` status in
`GET /api/duplicates`; a group-label decision resolves them. Matching labels
keep one visible representative. Human decisions remain append-only.

On a re-finding query with the same concepts, existing PMIDs get another
`query_records` link without an EFetch request; the human Exclude still wins.
Screen results are reused when query groups, criteria, record content and rule
version are unchanged. The screen run log now records `screened` and `reused`;
PICO records `tagged` and `tag_reused`. Editing one abstract rescreens that
record. Changing the query concepts invalidates screening for every record
linked to that changed query, because the current cache context includes all
query groups. Untagged Include records with zero generated spans cannot yet be
distinguished from records that were never tagged, so they may be retagged.

`scripts/seed_loop_demo.py` creates a fictional two-version example only in a
new empty database and refuses to touch populated data. It prints the two
required cases to demonstrate. This script uses authored synthetic records,
not PubMed evidence.
