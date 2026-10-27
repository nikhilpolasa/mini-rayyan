"""Fixed fictional examples shared by the stub routers; no persistence."""

STAMP = "2026-10-27T08:00:00Z"
QUERY_CREATED = {
    "id": 1,
    "version": 1,
    "hit_count": 42,
    "translation": "exercise[Title/Abstract] AND sleep[Title/Abstract]",
}
QUERY = {
    **QUERY_CREATED,
    "project_id": 1,
    "parent_id": None,
    "text": "exercise[tiab] AND sleep[tiab]",
    "date_from": "2016-01-01",
    "date_to": "2026-10-27",
    "status": "saved",
    "counts": {"records": 10, "include": 0, "exclude": 0, "maybe": 10},
    "created_at": STAMP,
}
APPROVAL = {"id": 1, "status": "approved"}
JOB = {"query_id": 1, "run_id": 1, "status": "queued"}
RECORD = {
    "id": 1,
    "pmid": "DEMO-0001",
    "doi": "10.0000/demo.1",
    "title": "Exercise and sleep quality in adults: a fictional trial",
    "year": 2024,
    "journal": "Fictional Evidence Journal",
    "label": "maybe",
    "reason": "Scaffold stub; screening has not run.",
    "criterion": "",
    "source": "machine",
    "hidden_duplicate": False,
}
RECORD_PAGE = {"items": [RECORD], "total": 1, "limit": 50, "offset": 0}
DECISION = {
    "id": 1,
    "entity_type": "record",
    "entity_id": 1,
    "action": "set_label",
    "old_value": {"label": "maybe"},
    "new_value": {"label": "include"},
    "note": "Reviewer checked the eligibility criteria.",
    "actor": "reviewer",
    "created_at": STAMP,
}
GROUP = {
    "id": 1,
    "representative_record_id": 1,
    "dedup_version": "dedup-v1",
    "rule_set_version": "dedup-v1",
    "run_id": 1,
    "members": [
        {"record_id": 1, "match_type": "exact", "score": 1.0, "status": "auto"},
        {"record_id": 2, "match_type": "exact", "score": 1.0, "status": "auto"},
    ],
}
DUPLICATES = {
    "groups": [GROUP],
    "uncertain_pairs": [
        {"record_ids": [3, 4], "score": 0.9, "match_type": "fuzzy", "status": "pending"}
    ],
}
RECORD_DETAIL = {
    **RECORD,
    "abstract": "Adults were assigned to exercise or usual care. Sleep quality was assessed after eight weeks.",
    "authors": ["Example A", "Sample B"],
    "language": "eng",
    "pub_types": ["Randomized Controlled Trial"],
    "mesh": ["Humans", "Adult"],
    "literature_source": "pubmed",
    "fetched_at": STAMP,
    "pico_spans": [],
    "group": GROUP,
    "decisions": [],
    "query_versions": [QUERY_CREATED],
}
RUN = {
    "id": 1,
    "query_id": 1,
    "step": "pipeline",
    "rule_set_version": "scaffold-v1",
    "status": "queued",
    "counts": {"records_in": 0},
    "started_at": STAMP,
    "finished_at": None,
}
CRITERION = {
    "key": "non_human",
    "project_id": 1,
    "label": "Non-human studies",
    "kind": "exclude",
    "description": "Exclude animal-only studies.",
    "reason": "The review concerns humans.",
    "source": "both",
    "active": True,
}
HEALTH = {"status": "ok"}
