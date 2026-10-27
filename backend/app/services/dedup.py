"""Versioned machine groups, projected with append-only human overrides."""

from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from . import matching
from .matching import AUTO_THRESHOLD, UNCERTAIN_THRESHOLD as PENDING_THRESHOLD

DEDUP_VERSION = "dedup-v3"


def record_dict(record: m.Record) -> dict:
    """Translate stored JSON columns to the shared record contract."""
    return {
        "id": record.id,
        "pmid": record.pmid,
        "doi": record.doi,
        "title": record.title,
        "abstract": record.abstract,
        "authors": record.authors_json,
        "year": record.year,
        "journal": record.journal,
        "language": record.language,
        "pub_types": record.pub_types_json,
        "mesh": record.mesh_json,
    }


def pair_key(a: int, b: int) -> str:
    """Return a stable pair identifier, independent of the query or run."""
    return ":".join(map(str, sorted((a, b))))


def components(
    ids: list[int], edges: dict, rejected: set | None = None
) -> list[list[int]]:
    """Build deterministic components without bridging explicitly rejected pairs."""
    groups = [{id} for id in ids]
    for a, b in sorted(edges):
        left = next(group for group in groups if a in group)
        right = next(group for group in groups if b in group)
        merged = left | right
        if left is right or any(
            set(pair).issubset(merged) for pair in rejected or set()
        ):
            continue
        groups.remove(right)
        left.update(right)
    return [sorted(group) for group in groups if len(group) > 1]


def build_groups(session: Session, run: m.RunLog) -> dict:
    """Score all stored pairs and reuse identical machine groups for this version."""
    records = list(session.scalars(select(m.Record).order_by(m.Record.id)))
    edges, pending = {}, []
    # ponytail: O(n²) over capped searches; add candidate blocking if profiling requires it.
    for a, b in combinations(records, 2):
        result = matching.pair_score(record_dict(a), record_dict(b))
        score, kind = result["score"], result["match_type"]
        if kind == "none":
            continue
        if kind not in {"exact", "fuzzy"} or not 0 <= score <= 1:
            raise ValueError("Invalid matching result")
        if kind == "exact" or score >= AUTO_THRESHOLD:
            edges[a.id, b.id] = (kind, score)
        elif score >= PENDING_THRESHOLD:
            pending.append(([a.id, b.id], "pending", kind, score))
    # Persist pair-sized groups so split components retain stable anchors.
    # The API projects their connected components as complete duplicate groups.
    specs = [(list(pair), "auto", kind, score) for pair, (kind, score) in edges.items()]
    specs.extend(pending)
    existing = set()
    for group in session.scalars(
        select(m.DupGroup).where(m.DupGroup.rule_set_version == run.rule_set_version)
    ):
        members = session.scalars(
            select(m.GroupMember)
            .where(m.GroupMember.group_id == group.id)
            .order_by(m.GroupMember.record_id)
        )
        existing.add(
            tuple(
                (member.record_id, member.status, member.match_type, member.score)
                for member in members
            )
        )
    for ids, status, kind, score in specs:
        if tuple((id, status, kind, score) for id in ids) in existing:
            continue
        group = m.DupGroup(
            representative_record_id=min(ids),
            dedup_version=run.rule_set_version,
            rule_set_version=run.rule_set_version,
            run_id=run.id,
        )
        session.add(group)
        session.flush()
        session.add_all(
            [
                m.GroupMember(
                    group_id=group.id,
                    record_id=id,
                    match_type=kind,
                    score=score,
                    status=status,
                    dedup_version=run.rule_set_version,
                    rule_set_version=run.rule_set_version,
                    run_id=run.id,
                )
                for id in ids
            ]
        )
    session.flush()
    return {
        "records_in": len(records),
        "groups_formed": len(components([r.id for r in records], edges)),
        "uncertain_pairs": len(pending),
    }


def state(session: Session) -> dict:
    """Compute effective groups/hidden IDs without changing machine or human rows."""
    run = session.scalar(
        select(m.RunLog)
        .where(m.RunLog.step == "dedup", m.RunLog.status == "completed")
        .order_by(m.RunLog.id.desc())
    )
    all_groups = {
        group.id: group
        for group in session.scalars(select(m.DupGroup).order_by(m.DupGroup.id))
    }
    members_by_group = {}
    for member in session.scalars(
        select(m.GroupMember).order_by(m.GroupMember.record_id)
    ):
        members_by_group.setdefault(member.group_id, []).append(member)
    edges, pending, rejected = {}, {}, set()
    for group in all_groups.values():
        if run is None or group.rule_set_version != run.rule_set_version:
            continue
        members = members_by_group.get(group.id, [])
        for pair in combinations(sorted(member.record_id for member in members), 2):
            metadata = {
                "score": min(member.score for member in members),
                "match_type": members[-1].match_type,
                "status": members[-1].status,
                "group_id": group.id,
            }
            (pending if metadata["status"] == "pending" else edges)[pair] = metadata
    decisions = list(
        session.scalars(
            select(m.Decision).order_by(m.Decision.created_at, m.Decision.id)
        )
    )
    for decision in decisions:
        value = decision.new_value
        if (
            decision.entity_type not in {"group", "pair"}
            or not isinstance(value, dict)
            or value.get("status") not in {"confirmed", "rejected", "pending", "auto"}
        ):
            continue
        ids = value.get("record_ids") or (
            [int(id) for id in decision.entity_id.split(":")]
            if decision.entity_type == "pair"
            else [
                member.record_id
                for member in members_by_group.get(int(decision.entity_id), [])
            ]
        )
        for pair in combinations(sorted(ids), 2):
            metadata = (
                edges.pop(pair, None)
                or pending.pop(pair, None)
                or {
                    "score": 1.0,
                    "match_type": "fuzzy",
                    "group_id": (
                        int(decision.entity_id)
                        if decision.entity_type == "group"
                        else None
                    ),
                }
            )
            metadata = {**metadata, "status": value["status"]}
            rejected.discard(pair)
            if value["status"] in {"auto", "confirmed"}:
                edges[pair] = metadata
            elif value["status"] == "pending":
                pending[pair] = metadata
            else:
                rejected.add(pair)
    ids = list(session.scalars(select(m.Record.id).order_by(m.Record.id)))
    effective_components = components(ids, edges, rejected)
    hidden, projected, membership, peers = set(), [], {}, {}
    for component in effective_components:
        group_ids = {
            id
            for id, members in members_by_group.items()
            if set(member.record_id for member in members).issubset(component)
        }
        anchors = [all_groups[id] for id in group_ids]
        labels = {}
        for decision in decisions:
            if (
                not isinstance(decision.new_value, dict)
                or "label" not in decision.new_value
            ):
                continue
            if (
                decision.entity_type == "record"
                and int(decision.entity_id) in component
            ):
                if decision.new_value.get("source") == "machine":
                    labels.pop(int(decision.entity_id), None)
                else:
                    labels[int(decision.entity_id)] = decision.new_value["label"]
            elif (
                decision.entity_type == "group" and int(decision.entity_id) in group_ids
            ):
                scope = set(decision.new_value.get("record_ids", component)) & set(
                    component
                )
                if decision.new_value.get("source") == "machine":
                    for id in scope:
                        labels.pop(id, None)
                else:
                    labels.update({id: decision.new_value["label"] for id in scope})
        conflict = len(set(labels.values())) > 1
        if not conflict:
            hidden.update(set(component) - {min(component)})
        output_members = []
        for id in component:
            values = [
                value
                for pair, value in edges.items()
                if id in pair and set(pair).issubset(component)
            ]
            output_members.append(
                {
                    "record_id": id,
                    "match_type": (
                        "fuzzy"
                        if any(v["match_type"] == "fuzzy" for v in values)
                        else "exact"
                    ),
                    "score": min(v["score"] for v in values),
                    "status": (
                        "pending"
                        if conflict
                        else (
                            "confirmed"
                            if any(v["status"] == "confirmed" for v in values)
                            else "auto"
                        )
                    ),
                }
            )
            membership[id] = group_ids
            peers[id] = {id} if conflict else set(component)
        if anchors:
            anchor = min(anchors, key=lambda group: group.id)
            projected.append(
                {
                    "id": anchor.id,
                    "representative_record_id": min(component),
                    "dedup_version": anchor.dedup_version,
                    "rule_set_version": anchor.rule_set_version,
                    "run_id": anchor.run_id,
                    "members": output_members,
                }
            )
    uncertain = [
        {
            "record_ids": list(pair),
            "score": value["score"],
            "match_type": "fuzzy",
            "status": "pending",
        }
        for pair, value in sorted(pending.items())
        if not any(set(pair).issubset(component) for component in effective_components)
    ]
    return {
        "hidden": hidden,
        "groups": projected,
        "uncertain_pairs": uncertain,
        "membership": membership,
        "peers": peers,
    }
