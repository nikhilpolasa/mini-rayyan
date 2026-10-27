"""Incremental fetch and deterministic, versioned dedup -> screen -> PICO jobs."""

import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from threading import RLock
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .. import models as m
from ..db import utc_now
from . import decisions, dedup, pico, pubmed, screening

SCREEN_VERSION = "screen-v2"
PICO_VERSION = "pico-v2"
PIPELINE_VERSION = "pipeline-v1"
# ponytail: serialize local jobs; add a durable queue/shared lock for multiple workers.
job_lock = RLock()


def fingerprint(prefix: str, data) -> str:
    """Derive stable context versions while retaining the algorithm version."""
    digest = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


@contextmanager
def source_client():
    """Choose the configured source and close live clients on every path."""
    mode = os.getenv("SOURCE_MODE", "live")
    if mode == "live":
        client = pubmed.LiveSourceClient()
    elif mode == "snapshot":
        client = pubmed.SnapshotSourceClient()
    else:
        raise ValueError("SOURCE_MODE must be live or snapshot")
    try:
        yield client
    finally:
        if hasattr(client, "close"):
            client.close()


def query_groups(text: str) -> list[list[str]]:
    """Split top-level AND outside quotes/brackets and extract positive terms.

    Field tags and Boolean operators are syntax, not relevance terms. NOT terms
    are excluded from positive concept groups. The original query is sent to
    PubMed unchanged. Outer parentheses around the whole query are supported.
    """
    tokens = re.findall(
        r'"[^"\\]*(?:\\.[^"\\]*)*"|\[[^\]]*\]|\(|\)|\b(?:AND|OR|NOT)\b|[^\s()\[\]"]+',
        text,
        re.I,
    )
    while tokens and tokens[0] == "(" and tokens[-1] == ")":
        depth = 0
        encloses_all = True
        for index, token in enumerate(tokens):
            depth += (token == "(") - (token == ")")
            if depth == 0 and index != len(tokens) - 1:
                encloses_all = False
                break
        if not encloses_all:
            break
        tokens = tokens[1:-1]
    chunks, current, depth = [], [], 0
    for token in tokens:
        if token.upper() == "AND" and depth == 0:
            chunks.append(current)
            current = []
        else:
            current.append(token)
        depth += (token == "(") - (token == ")")
    chunks.append(current)
    groups = []
    for chunk in chunks:
        terms, phrase, negated, negative_depth, depth = [], [], False, None, 0

        def flush():
            if phrase:
                terms.append(" ".join(phrase))
                phrase.clear()

        for token in chunk:
            upper = token.upper()
            if upper == "NOT":
                flush()
                negated = True
                continue
            if token == "(":
                flush()
                depth += 1
                if negated and negative_depth is None:
                    negative_depth = depth
            elif token == ")":
                flush()
                if negative_depth == depth:
                    negated, negative_depth = False, None
                depth -= 1
            elif upper in {"OR", "AND"}:
                flush()
                if negative_depth is None:
                    negated = False
            elif token.startswith("["):
                flush()
            elif not negated:
                if token.startswith('"'):
                    flush()
                    terms.append(token[1:-1])
                else:
                    phrase.append(token)
        flush()
        if terms:
            groups.append(list(dict.fromkeys(term for term in terms if term)))
    return groups


def enqueue(session: Session, query_id: int, step: str) -> m.RunLog:
    """Persist a queued job and reject invalid lifecycle transitions."""
    query = session.get(m.Query, query_id)
    if query is None:
        raise LookupError("Query not found")
    if step == "fetch" and query.status not in {"approved", "fetched"}:
        raise ValueError("Approve the query before fetching")
    if step == "pipeline" and query.status != "fetched":
        raise ValueError("Fetch the query before running the pipeline")
    busy = session.scalar(
        select(m.RunLog.id).where(
            m.RunLog.query_id == query_id,
            m.RunLog.step.in_(["fetch", "pipeline"]),
            m.RunLog.status.in_(["queued", "running"]),
        )
    )
    if busy:
        raise ValueError("A job is already queued or running for this query")
    run = m.RunLog(
        query_id=query_id,
        step=step,
        rule_set_version="fetch-v1" if step == "fetch" else PIPELINE_VERSION,
        status="queued",
        counts_json={},
    )
    session.add(run)
    if step == "fetch":
        query.status = "fetching"
    session.commit()
    session.refresh(run)
    return run


def _insert_record(session: Session, data: dict) -> m.Record:
    """Insert missing PMIDs, preserving the canonical stored text on conflicts."""
    existing = session.scalar(select(m.Record).where(m.Record.pmid == data["pmid"]))
    if existing:
        return existing
    record = m.Record(
        **{
            key: data.get(key)
            for key in [
                "pmid",
                "doi",
                "title",
                "abstract",
                "year",
                "journal",
                "language",
            ]
        },
        authors_json=data.get("authors") or [],
        pub_types_json=data.get("pub_types") or [],
        mesh_json=data.get("mesh") or [],
        source=data.get("source", "pubmed"),
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
        return record
    except IntegrityError:
        record = session.scalar(select(m.Record).where(m.Record.pmid == data["pmid"]))
        if record is None:
            raise
        return record


def fetch(session: Session, query: m.Query) -> dict:
    """Fetch only unseen IDs, but link all returned existing/new records."""
    cap = max(0, int(os.getenv("FETCH_CAP", "500")))
    with source_client() as client:
        ids = list(
            dict.fromkeys(
                client.search_ids(query.text, query.date_from, query.date_to, limit=cap)
            )
        )[:cap]
        existing = {
            record.pmid: record
            for record in session.scalars(select(m.Record))
            if record.pmid in set(ids)
        }
        missing = [pmid for pmid in ids if pmid not in existing]
        data = client.fetch_records(missing) if missing else []
    added = 0
    for record_data in data:
        if record_data["pmid"] not in missing:
            continue
        record = _insert_record(session, record_data)
        if record.pmid not in existing:
            existing[record.pmid] = record
            added += 1
    linked = 0
    for pmid in ids:
        record = existing.get(pmid)
        if record is None:
            continue  # PubMed may omit a withdrawn/book record.
        if session.get(m.QueryRecord, (query.id, record.id)) is None:
            try:
                with session.begin_nested():
                    session.add(m.QueryRecord(query_id=query.id, record_id=record.id))
                    session.flush()
                linked += 1
            except IntegrityError:
                if session.get(m.QueryRecord, (query.id, record.id)) is None:
                    raise
    query.status = "fetched"
    return {
        "records_in": len(ids),
        "records_added": added,
        "records_reused": len(ids) - len(missing),
        "links_added": linked,
        "records_missing": len(ids) - len(existing),
    }


def _step(session: Session, query_id: int, step: str, version: str, operation) -> dict:
    """Commit a step's outputs atomically and retain failures in the run log."""
    run = m.RunLog(
        query_id=query_id,
        step=step,
        rule_set_version=version,
        status="running",
        counts_json={},
    )
    session.add(run)
    session.commit()
    run_id, start = run.id, perf_counter()
    try:
        counts = operation(run)
        run.counts_json = {**counts, "seconds": round(perf_counter() - start, 6)}
        run.finished_at, run.status = utc_now(), "completed"
        session.commit()
        return counts
    except Exception:
        session.rollback()
        run = session.get(m.RunLog, run_id)
        run.status, run.finished_at = "failed", utc_now()
        run.counts_json = {"seconds": round(perf_counter() - start, 6)}
        session.commit()
        raise


def process(session: Session, query: m.Query) -> dict:
    """Dedup globally, screen visible query records, then tag effective Includes."""
    records = list(
        session.scalars(
            select(m.Record)
            .join(m.QueryRecord)
            .where(m.QueryRecord.query_id == query.id)
            .order_by(m.Record.id)
        )
    )
    all_records = [
        dedup.record_dict(record)
        for record in session.scalars(select(m.Record).order_by(m.Record.id))
    ]
    dedup_version = fingerprint(dedup.DEDUP_VERSION, all_records)
    counts = _step(
        session,
        query.id,
        "dedup",
        dedup_version,
        lambda run: dedup.build_groups(session, run),
    )
    state = dedup.state(session)
    visible = [record for record in records if record.id not in state["hidden"]]
    criteria = list(
        session.scalars(
            select(m.Criterion)
            .where(m.Criterion.project_id == query.project_id)
            .order_by(m.Criterion.key)
        )
    )
    screen_version = fingerprint(
        SCREEN_VERSION,
        [
            {key: value for key, value in decisions.columns(criterion).items()}
            for criterion in criteria
        ],
    )
    active = [criterion.key for criterion in criteria if criterion.active]
    groups = query_groups(query.text)

    def screen_step(run):
        processed, excluded = 0, 0
        for record in visible:
            if session.scalar(
                select(m.ScreenResult.id).where(
                    m.ScreenResult.record_id == record.id,
                    m.ScreenResult.rule_set_version == screen_version,
                )
            ):
                continue
            result = screening.screen(
                {**dedup.record_dict(record), "query_groups": groups}, active
            )
            if result.get("label") not in decisions.LABELS or (
                result["label"] == "exclude"
                and (not result.get("reason") or not result.get("criterion"))
            ):
                raise ValueError("Invalid screening result")
            session.add(
                m.ScreenResult(
                    record_id=record.id,
                    rule_set_version=screen_version,
                    run_id=run.id,
                    label=result["label"],
                    reason=result["reason"],
                    criterion=result["criterion"],
                )
            )
            processed += 1
            excluded += result["label"] == "exclude"
        session.flush()
        return {
            "records_in": len(visible),
            "records_screened": processed,
            "auto_excluded": excluded,
        }

    counts.update(_step(session, query.id, "screen", screen_version, screen_step))
    pico_version = fingerprint(
        PICO_VERSION, {"groups": groups, "screen_version": screen_version}
    )

    def pico_step(run):
        processed, tagged = 0, 0
        for record in visible:
            if (
                decisions.effective_status(
                    session,
                    record.id,
                    state["membership"].get(record.id),
                    screen_version,
                    peer_ids=state["peers"].get(record.id),
                )["label"]
                != "include"
            ):
                continue
            if session.scalar(
                select(m.PicoSpan.id).where(
                    m.PicoSpan.record_id == record.id,
                    m.PicoSpan.pico_version == pico_version,
                    m.PicoSpan.source == "machine",
                )
            ):
                continue
            spans = pico.tag_pico(
                record.abstract or "", [term for group in groups for term in group]
            )
            for span in spans:
                decisions.validate_span(record.abstract or "", span)
                session.add(
                    m.PicoSpan(
                        record_id=record.id,
                        pico_version=pico_version,
                        rule_set_version=pico_version,
                        run_id=run.id,
                        source="machine",
                        **span,
                    )
                )
            processed += 1
            tagged += len(spans)
        session.flush()
        return {"records_tagged": processed, "pico_spans_added": tagged}

    counts.update(_step(session, query.id, "pico", pico_version, pico_step))
    return counts


def execute(run_id: int, bind) -> None:
    """Background entry point with its own session; never borrow request sessions."""
    with job_lock, sessionmaker(bind=bind, expire_on_commit=False)() as session:
        run = session.get(m.RunLog, run_id)
        if run is None or run.status != "queued":
            return
        run.status, run.started_at = "running", utc_now()
        session.commit()
        start = perf_counter()
        try:
            query = session.get(m.Query, run.query_id)
            counts = (
                fetch(session, query)
                if run.step == "fetch"
                else process(session, query)
            )
            run.counts_json = {**counts, "seconds": round(perf_counter() - start, 6)}
            run.status = "completed"
        except Exception as exc:
            session.rollback()
            run = session.get(m.RunLog, run_id)
            run.status = "failed"
            run.counts_json = {"seconds": round(perf_counter() - start, 6)}
            if run.step == "fetch":
                session.get(m.Query, run.query_id).status = "failed"
            logging.error("%s job %d failed (%s)", run.step, run_id, type(exc).__name__)
        run.finished_at = utc_now()
        session.commit()
