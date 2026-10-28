"""PRD tables; no record deletion or human-decision mutation helpers."""

from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utc_now


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Query(Base):
    __tablename__ = "queries"
    __table_args__ = (
        UniqueConstraint("project_id", "version"),
        CheckConstraint("status IN ('saved','approved','fetching','fetched','failed')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(default=1)
    version: Mapped[int]
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("queries.id"))
    text: Mapped[str] = mapped_column(Text)
    date_from: Mapped[date]
    date_to: Mapped[date]
    hit_count: Mapped[int] = mapped_column(default=0)
    query_translation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="saved")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Record(Base):
    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True)
    pmid: Mapped[str] = mapped_column(unique=True)
    doi: Mapped[str | None]
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[list] = mapped_column(JSON, default=list)
    year: Mapped[int | None]
    journal: Mapped[str | None]
    language: Mapped[str | None]
    pub_types_json: Mapped[list] = mapped_column(JSON, default=list)
    mesh_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(default="pubmed")
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class QueryRecord(Base):
    __tablename__ = "query_records"

    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id"), primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"), primary_key=True)
    found_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class RunLog(Base):
    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(ForeignKey("queries.id"))
    step: Mapped[str]
    rule_set_version: Mapped[str]
    status: Mapped[str]
    counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DupGroup(Base):
    __tablename__ = "dup_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    representative_record_id: Mapped[int] = mapped_column(ForeignKey("records.id"))
    dedup_version: Mapped[str]
    # AGENTS section 2 requires version and run provenance on machine outputs.
    rule_set_version: Mapped[str]
    run_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"))


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        CheckConstraint("match_type IN ('exact','fuzzy')"),
        CheckConstraint("status IN ('auto','pending','confirmed','rejected')"),
        CheckConstraint("score >= 0 AND score <= 1"),
    )

    group_id: Mapped[int] = mapped_column(ForeignKey("dup_groups.id"), primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"), primary_key=True)
    match_type: Mapped[str]
    score: Mapped[float]
    status: Mapped[str]
    dedup_version: Mapped[str]
    rule_set_version: Mapped[str]
    run_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"))


class Criterion(Base):
    __tablename__ = "criteria"
    __table_args__ = (CheckConstraint("source IN ('metadata','algorithm','both')"),)

    key: Mapped[str] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(default=1)
    label: Mapped[str]
    kind: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)


class ScreenResult(Base):
    __tablename__ = "screen_results"
    __table_args__ = (
        UniqueConstraint("record_id", "rule_set_version"),
        CheckConstraint("label IN ('include','exclude','maybe')"),
        CheckConstraint(
            "label != 'exclude' OR (length(reason) > 0 AND length(criterion) > 0)"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"))
    rule_set_version: Mapped[str]
    label: Mapped[str]
    reason: Mapped[str] = mapped_column(Text)
    criterion: Mapped[str]
    run_id: Mapped[int] = mapped_column(ForeignKey("run_log.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class PicoSpan(Base):
    __tablename__ = "pico_spans"
    __table_args__ = (
        CheckConstraint("label IN ('P','I','C','O')"),
        CheckConstraint("source IN ('machine','human')"),
        CheckConstraint('start >= 0 AND "end" > start'),
        CheckConstraint("source != 'machine' OR run_id IS NOT NULL"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id"))
    pico_version: Mapped[str]
    label: Mapped[str]
    start: Mapped[int]
    end: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str]
    rule_set_version: Mapped[str]
    run_id: Mapped[int | None] = mapped_column(ForeignKey("run_log.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('record','group','pair','pico_span','criterion')"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str]
    entity_id: Mapped[str]
    action: Mapped[str]
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON
    )
    new_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON
    )
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(default="reviewer")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
