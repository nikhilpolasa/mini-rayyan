"""Read-only projections for a stored query version's records and groups."""

import hashlib
import json
from itertools import combinations

from sqlalchemy import select

from .. import models as m
from . import decisions, dedup


def _pair_choices(session, ids: set[int]) -> tuple[set, set]:
    choices = {}
    for decision in session.scalars(select(m.Decision).order_by(m.Decision.created_at, m.Decision.id)):
        if decision.entity_type not in {"pair", "group"} or not isinstance(decision.new_value, dict):
            continue
        status = decision.new_value.get("status")
        if status not in {"confirmed", "rejected", "pending", "auto"}:
            continue
        members = decision.new_value.get("record_ids")
        if not members and decision.entity_type == "pair":
            try:
                members = [int(id) for id in decision.entity_id.split(":")]
            except ValueError:
                continue
        if not members and decision.entity_type == "group":
            members = list(session.scalars(select(m.GroupMember.record_id).where(m.GroupMember.group_id == int(decision.entity_id))))
        for pair in combinations(sorted(set(members or [])), 2):
            if set(pair) <= ids:
                choices[pair] = status
    return (
        {pair for pair, status in choices.items() if status == "rejected"},
        {pair for pair, status in choices.items() if status in {"confirmed", "auto"}},
    )


def as_of(session, query_id: int) -> dict:
    records = list(session.scalars(select(m.Record).join(m.QueryRecord).where(m.QueryRecord.query_id == query_id).order_by(m.Record.id)))
    ids = {record.id for record in records}
    rejected, confirmed = _pair_choices(session, ids)
    groups = dedup.compute_groups([dedup.record_dict(record) for record in records], rejected, confirmed)
    peers = {id: set(group["members"]) for group in groups for id in group["members"]}
    labels = {
        record.id: decisions.effective_status(session, record.id, peer_ids=peers[record.id], query_id=query_id)
        for record in records
    }
    structure = {"record_ids": sorted(ids), "groups": groups}
    return {
        "query_id": query_id,
        **structure,
        "effective_labels": labels,
        "state_hash": hashlib.sha256(json.dumps(structure, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def diff(session, query_id: int, base_id: int) -> dict:
    current, base = as_of(session, query_id), as_of(session, base_id)
    current_ids, base_ids = set(current["record_ids"]), set(base["record_ids"])
    added, removed, common = sorted(current_ids - base_ids), sorted(base_ids - current_ids), sorted(current_ids & base_ids)
    base_group_by_member = {id: group["representative_record_id"] for group in base["groups"] for id in group["members"]}
    combined_ids = current_ids | base_ids
    combined_records = list(session.scalars(select(m.Record).where(m.Record.id.in_(combined_ids)).order_by(m.Record.id)))
    rejected, confirmed = _pair_choices(session, combined_ids)
    combined_groups = dedup.compute_groups([dedup.record_dict(record) for record in combined_records], rejected, confirmed)
    merged = []
    for group in combined_groups:
        members = group["members"]
        old_groups = sorted({base_group_by_member[id] for id in members if id in base_group_by_member})
        if len(members) > 1 and (len(old_groups) > 1 or (old_groups and any(id in added for id in members))):
            merged.append({"representative_record_id": group["representative_record_id"], "member_ids": members, "base_group_ids": old_groups})
    human = set()
    for decision in session.scalars(select(m.Decision)):
        if decision.entity_type == "record" and int(decision.entity_id) in common:
            human.add(int(decision.entity_id))
        elif decision.entity_type == "group" and isinstance(decision.new_value, dict):
            human.update(set(decision.new_value.get("record_ids", [])) & set(common))
        elif decision.entity_type == "pico_span" and isinstance(decision.new_value, dict):
            if decision.new_value.get("record_id") in common:
                human.add(decision.new_value["record_id"])
        elif decision.entity_type == "pair":
            try:
                human.update({int(id) for id in decision.entity_id.split(":")} & set(common))
            except ValueError:
                pass
    return {
        "query_id": query_id, "base_query_id": base_id,
        "records_added": added, "records_removed": removed, "records_common": common,
        "groups_newly_merged": merged,
        "counts": {"added": len(added), "removed": len(removed), "common": len(common), "groups_newly_merged": len(merged)},
        "added_effective_labels": {id: current["effective_labels"][id] for id in added},
        "common_with_human_decision": sorted(human),
    }
