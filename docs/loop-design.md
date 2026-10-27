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

Exact revert, query-version diff views, durable job recovery and incremental
processing of externally updated abstracts are Level 2 work. Stored provenance
supports them, but their presence in this design is not a claim of implementation.
