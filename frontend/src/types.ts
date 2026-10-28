export type Label = 'include' | 'exclude' | 'maybe';
export type Source = 'machine' | 'human';
export type QueryStatus = 'saved' | 'approved' | 'fetching' | 'fetched' | 'failed';
export interface QueryInput { text: string; date_from: string; date_to: string; project_id?: number; parent_id?: number | null }
export interface Project { id: number; title: string; created_at: string }
export interface QueryCreated { id: number; version: number; hit_count: number; translation: string }
export interface QueryVersion extends QueryCreated, QueryInput {
  project_id: number; parent_id: number | null; status: QueryStatus;
  counts: Record<string, number>; created_at: string;
}
export interface RecordSummary {
  id: number; pmid: string; doi: string | null; title: string; year: number | null;
  journal: string | null; label: Label; reason: string; criterion: string;
  source: Source; hidden_duplicate: boolean;
}
export interface PicoSpan {
  id: number; label: 'P' | 'I' | 'C' | 'O'; start: number; end: number; text: string;
  source: Source; pico_version: string; rule_set_version: string; run_id: number | null;
}
export interface Member { record_id: number; match_type: 'exact' | 'fuzzy'; score: number; status: 'auto' | 'pending' | 'confirmed' | 'rejected' }
export interface DuplicateGroup { id: number; representative_record_id: number; dedup_version: string; rule_set_version: string; run_id: number; members: Member[] }
export interface Duplicates { groups: DuplicateGroup[]; uncertain_pairs: { record_ids: number[]; score: number; match_type: 'fuzzy'; status: 'pending' }[] }
export interface DecisionInput {
  entity_type: 'record' | 'group' | 'pair' | 'pico_span' | 'criterion';
  entity_id: number | string; action: string; new_value: unknown; note?: string;
}
export interface Decision extends DecisionInput { id: number; old_value: unknown; actor: string; created_at: string; note: string }
export interface RecordDetail extends RecordSummary {
  abstract: string | null; authors: string[]; language: string | null; pub_types: string[];
  mesh: string[]; literature_source: string; fetched_at: string; pico_spans: PicoSpan[];
  group: DuplicateGroup | null; decisions: Decision[]; query_versions: QueryCreated[];
}
export interface RecordPage { items: RecordSummary[]; total: number; limit: number; offset: number }
export interface RecordFilters { query_id?: number; label?: Label; show_hidden?: boolean; limit?: number; offset?: number }
export interface Run {
  id: number; query_id: number; step: string; rule_set_version: string;
  status: 'queued' | 'running' | 'completed' | 'failed'; counts: Record<string, number>;
  started_at: string; finished_at: string | null;
}
export interface Job { query_id: number; run_id: number; status: 'queued' }
export interface Criterion { key: string; project_id: number; label: string; kind: string; description: string; reason: string; source: 'metadata' | 'algorithm' | 'both'; active: boolean }
