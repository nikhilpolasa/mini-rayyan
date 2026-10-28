"""Request/response contracts for the scaffold API."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

Label = Literal["include", "exclude", "maybe"]
QueryStatus = Literal["saved", "approved", "fetching", "fetched", "failed"]
EntityType = Literal["record", "group", "pair", "pico_span", "criterion"]


class QueryCreate(BaseModel):
    text: str = Field(min_length=1)
    date_from: date
    date_to: date
    project_id: int | None = Field(default=None, gt=0)
    parent_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_to < self.date_from:
            raise ValueError("date_to must be on or after date_from")
        return self


class QueryCreated(BaseModel):
    id: int
    version: int
    hit_count: int
    translation: str


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    id: int
    title: str
    created_at: datetime


class QueryDetail(QueryCreated, QueryCreate):
    project_id: int = 1
    parent_id: int | None
    status: QueryStatus
    counts: dict[str, int]
    created_at: datetime


class QueryApproval(BaseModel):
    id: int
    status: Literal["approved"]


class JobStarted(BaseModel):
    query_id: int
    run_id: int
    status: Literal["queued"]


class DecisionCreate(BaseModel):
    entity_type: EntityType
    entity_id: int | str
    action: str = Field(min_length=1)
    new_value: JsonValue
    note: str = ""


class DecisionOut(DecisionCreate):
    id: int
    old_value: JsonValue
    actor: str
    created_at: datetime


class PicoSpanOut(BaseModel):
    id: int
    label: Literal["P", "I", "C", "O"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    source: Literal["machine", "human"]
    pico_version: str
    rule_set_version: str
    run_id: int | None


class RecordSummary(BaseModel):
    id: int
    pmid: str
    doi: str | None
    title: str
    year: int | None
    journal: str | None
    label: Label
    reason: str
    criterion: str
    source: Literal["machine", "human"]
    hidden_duplicate: bool


class RecordPage(BaseModel):
    items: list[RecordSummary]
    total: int
    limit: int
    offset: int


class DuplicateMember(BaseModel):
    record_id: int
    match_type: Literal["exact", "fuzzy"]
    score: float = Field(ge=0, le=1)
    status: Literal["auto", "pending", "confirmed", "rejected"]


class DuplicateGroup(BaseModel):
    id: int
    representative_record_id: int
    dedup_version: str
    rule_set_version: str
    run_id: int
    members: list[DuplicateMember]


class UncertainPair(BaseModel):
    record_ids: list[int] = Field(min_length=2, max_length=2)
    score: float = Field(ge=0, le=1)
    match_type: Literal["fuzzy"]
    status: Literal["pending"]


class DuplicatesOut(BaseModel):
    groups: list[DuplicateGroup]
    uncertain_pairs: list[UncertainPair]


class RecordDetail(RecordSummary):
    abstract: str | None
    authors: list[str]
    language: str | None
    pub_types: list[str]
    mesh: list[str]
    literature_source: str
    fetched_at: datetime
    pico_spans: list[PicoSpanOut]
    group: DuplicateGroup | None
    decisions: list[DecisionOut]
    query_versions: list[QueryCreated]


class RunOut(BaseModel):
    id: int
    query_id: int
    step: str
    rule_set_version: str
    status: Literal["queued", "running", "completed", "failed"]
    counts: dict[str, int | float]
    started_at: datetime
    finished_at: datetime | None


class CriterionPatch(BaseModel):
    active: bool


class CriterionOut(CriterionPatch):
    key: str
    project_id: int = 1
    label: str
    kind: str
    description: str
    reason: str
    source: Literal["metadata", "algorithm", "both"]


class HealthOut(BaseModel):
    status: Literal["ok"]
