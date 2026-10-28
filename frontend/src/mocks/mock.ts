/** Browser-local fixture adapter. No external HTTP; samples originate in docs/api-examples.json. */
import examples from './api-examples.json';
import type { Criterion, Decision, DecisionInput, Duplicates, Job, Label, PicoSpan, Project, QueryInput, QueryVersion, RecordDetail, Run } from '../types';

function example<T>(path: string): T {
  const endpoint = examples.endpoints.find(item => item.method === 'GET' && item.path.split('?')[0] === path);
  if (!endpoint) throw new Error(`Missing mock fixture: ${path}`);
  return structuredClone(endpoint.response) as T;
}
type State = { projects: Project[]; queries: QueryVersion[]; records: RecordDetail[]; criteria: Criterion[]; duplicates: Duplicates; decisions: Decision[]; runs: Run[]; links: Record<string, number[]>; jobs: { id: number; finish: number }[] };
const storageKey = 'mini-rayyan-mock-v1';
const now = () => new Date().toISOString();
const idNext = (items: { id: number }[]) => Math.max(0, ...items.map(item => item.id)) + 1;
const object = (value: unknown) => typeof value === 'object' && value !== null ? value as Record<string, unknown> : {};
const validLabels = ['include', 'exclude', 'maybe'];

function initialState(): State {
  const queries = example<QueryVersion[]>('/api/queries');
  const first = example<RecordDetail>('/api/records/1');
  const duplicates = example<Duplicates>('/api/duplicates');
  const ids = [...new Set([first.id, ...duplicates.groups.flatMap(group => group.members.map(member => member.record_id)), ...duplicates.uncertain_pairs.flatMap(pair => pair.record_ids)])];
  // Hydrate IDs referenced by the duplicate fixture; their unavailable metadata is explicit.
  const records = ids.map(id => id === first.id ? first : {
    ...structuredClone(first), id, pmid: `DEMO-${String(id).padStart(4, '0')}`, doi: null,
    title: `Fictional candidate ${id} · metadata not supplied in the example`, abstract: null,
    authors: [], pico_spans: [], decisions: [], group: null, query_versions: [queries[0]],
  });
  return { projects: [{ id: 1, title: 'Imported history (legacy)', created_at: queries[0]?.created_at ?? now() }], queries, records, criteria: example<Criterion[]>('/api/criteria'), duplicates,
    decisions: example<Decision[]>('/api/decisions'), runs: [], links: { '1': ids }, jobs: [] };
}

function load(): State {
  try {
    const saved = sessionStorage.getItem(storageKey);
    if (saved) { const state = JSON.parse(saved) as State; if (Array.isArray(state.queries) && Array.isArray(state.jobs)) { state.projects ??= [{ id: 1, title: 'Imported history (legacy)', created_at: state.queries[0]?.created_at ?? now() }]; return state; } }
  } catch { /* Storage may be unavailable; keep a session in memory. */ }
  return initialState();
}
let state = load();
function persist() { try { sessionStorage.setItem(storageKey, JSON.stringify(state)); } catch { /* Private browsing fallback. */ } }
export function resetMock() { state = initialState(); persist(); }
function requireItem<T>(items: T[], predicate: (item: T) => boolean, name: string): T {
  const result = items.find(predicate); if (!result) throw new Error(`${name} not found in the mock workspace.`); return result;
}
function hideDuplicates() {
  state.records.forEach(record => { record.hidden_duplicate = false; record.group = null; });
  for (const group of state.duplicates.groups) for (const member of group.members) {
    const record = state.records.find(record => record.id === member.record_id);
    if (record) { record.group = group; record.hidden_duplicate = member.record_id !== group.representative_record_id && ['auto', 'confirmed'].includes(member.status); }
  }
}
function recordView(record: RecordDetail): RecordDetail {
  const result = structuredClone(record);
  for (const decision of state.decisions) {
    const value = object(decision.new_value);
    const applies = decision.entity_type === 'record' && String(decision.entity_id) === String(record.id)
      || decision.entity_type === 'group' && record.group?.id === Number(decision.entity_id);
    if (applies && validLabels.includes(String(value.label))) {
      result.label = value.label as Label; result.source = value.source === 'machine' ? 'machine' : 'human'; result.reason = String(value.reason ?? decision.note); result.criterion = String(value.criterion ?? '');
    }
  }
  result.decisions = state.decisions.filter(decision => decision.entity_type === 'record' && String(decision.entity_id) === String(record.id) || decision.entity_type === 'pico_span' && object(decision.new_value).record_id === record.id);
  result.query_versions = state.queries.filter(query => state.links[query.id]?.includes(record.id));
  return result;
}
function refreshCounts() {
  hideDuplicates();
  for (const query of state.queries) {
    const records = state.records.filter(record => state.links[query.id]?.includes(record.id)).map(recordView);
    query.counts = { records: records.length, ...Object.fromEntries(validLabels.map(label => [label, records.filter(record => record.label === label && !record.hidden_duplicate).length])) };
  }
}
function settleJobs() {
  for (const job of state.jobs.filter(job => job.finish <= Date.now())) {
    const run = state.runs.find(run => run.id === job.id)!;
    const query = state.queries.find(query => query.id === run.query_id)!;
    if (run.step === 'fetch') { query.status = 'fetched'; state.links[query.id] = state.records.map(record => record.id); }
    run.status = 'completed'; run.finished_at = now(); run.counts = { records_in: state.records.length, records_added: 0, seconds: 1.2 };
    if (run.step === 'pipeline') for (const step of ['dedup', 'screen', 'pico']) state.runs.push({ ...run, id: idNext(state.runs), step, rule_set_version: `${step}-v1`, counts: { records_in: state.records.length, seconds: 0 } });
  }
  state.jobs = state.jobs.filter(job => job.finish > Date.now());
  refreshCounts(); persist();
}

function startJob(query: QueryVersion, step: string): Job {
  if (state.runs.some(run => run.query_id === query.id && ['queued', 'running'].includes(run.status))) throw new Error('A job is already running for this query.');
  if (step === 'fetch' && !['approved', 'fetched'].includes(query.status)) throw new Error('Approve this query before pulling abstracts.');
  if (step === 'pipeline' && query.status !== 'fetched') throw new Error('Pull abstracts before running the pipeline.');
  const run: Run = { id: idNext(state.runs), query_id: query.id, step, rule_set_version: `${step}-v1`, status: 'running', counts: {}, started_at: now(), finished_at: null };
  state.runs.push(run); state.jobs.push({ id: run.id, finish: Date.now() + 1200 });
  if (step === 'fetch') query.status = 'fetching';
  return { query_id: query.id, run_id: run.id, status: 'queued' };
}

function decide(input: DecisionInput): Decision {
  const previous = [...state.decisions].reverse().find(decision => decision.entity_type === input.entity_type && String(decision.entity_id) === String(input.entity_id));
  let value = input.action === 'undo' ? previous?.old_value : input.new_value;
  if (input.action === 'undo' && !previous) throw new Error('No decision to undo for this item.');
  let old: unknown = previous?.new_value ?? null;
  if (input.entity_type === 'record') {
    const record = recordView(requireItem(state.records, record => record.id === Number(input.entity_id), 'Record'));
    old = { label: record.label, source: record.source, reason: record.reason, criterion: record.criterion };
    if (input.action === 'note') { old = { note: previous?.note ?? '' }; value = { note: input.note }; }
  } else if (input.entity_type === 'criterion') {
    const criterion = requireItem(state.criteria, criterion => criterion.key === input.entity_id, 'Criterion');
    old = { active: criterion.active }; criterion.active = Boolean(object(value).active);
  } else if (input.entity_type === 'pair' || input.entity_type === 'group') {
    const ids = input.entity_type === 'pair' ? String(input.entity_id).split(':').map(Number) : requireItem(state.duplicates.groups, group => group.id === Number(input.entity_id), 'Group').members.map(member => member.record_id);
    const group = state.duplicates.groups.find(group => ids.every(id => group.members.some(member => member.record_id === id)));
    old = previous?.new_value ?? { status: group ? 'auto' : 'pending' };
    if (input.action !== 'undo' && ['confirm', 'reject', 'merge', 'split'].includes(input.action)) value = { status: ['confirm', 'merge'].includes(input.action) ? 'confirmed' : 'rejected' };
    const status = object(value).status;
    state.duplicates.uncertain_pairs = state.duplicates.uncertain_pairs.filter(pair => !ids.every(id => pair.record_ids.includes(id)));
    if (status === 'confirmed' && !group) state.duplicates.groups.push({ id: idNext(state.duplicates.groups), representative_record_id: Math.min(...ids), dedup_version: 'human', rule_set_version: 'human', run_id: 0, members: ids.map(id => ({ record_id: id, score: 1, match_type: 'fuzzy', status: 'confirmed' })) });
    else if (group && typeof status === 'string') group.members.forEach(member => { member.status = status as typeof member.status; });
    if (status === 'pending') state.duplicates.uncertain_pairs.push({ record_ids: ids, score: 0.9, match_type: 'fuzzy', status: 'pending' });
  } else if (input.entity_type === 'pico_span') {
    const data = object(value);
    const targetSpanId = input.action === 'undo' ? Number(object(previous?.new_value).span_id ?? object(previous?.new_value).id ?? input.entity_id) : Number(input.entity_id);
    const record = input.action === 'add' ? requireItem(state.records, record => record.id === Number(data.record_id), 'Record') : requireItem(state.records, record => record.pico_spans.some(span => span.id === targetSpanId) || record.id === Number(data.record_id), 'Record');
    const span = input.action === 'add' ? undefined : record.pico_spans.find(span => span.id === targetSpanId);
    old = span ? { ...span, record_id: record.id } : { record_id: record.id, removed: true };
    if (input.action === 'remove' || data.removed) { value = { record_id: record.id, span_id: targetSpanId, removed: true }; record.pico_spans = record.pico_spans.filter(span => span.id !== targetSpanId); }
    else {
      const fields = { ...span, ...data };
      const chars = Array.from(record.abstract ?? '');
      if (!['P', 'I', 'C', 'O'].includes(String(fields.label)) || typeof fields.start !== 'number' || typeof fields.end !== 'number' || fields.start < 0 || fields.end <= fields.start || fields.end > chars.length || chars.slice(fields.start, fields.end).join('') !== fields.text) throw new Error('PICO offsets must match the exact abstract text.');
      const next: PicoSpan = { id: span?.id ?? Math.max(0, ...state.records.flatMap(record => record.pico_spans.map(span => span.id))) + 1, label: fields.label as PicoSpan['label'], start: fields.start, end: fields.end, text: String(fields.text), source: 'human', pico_version: 'human', rule_set_version: 'human', run_id: null };
      record.pico_spans = [...record.pico_spans.filter(item => item.id !== next.id), next]; value = { ...next, record_id: record.id, span_id: next.id };
    }
  }
  const decision: Decision = { ...input, id: idNext(state.decisions), old_value: structuredClone(old), new_value: structuredClone(value), note: input.note ?? '', actor: 'reviewer', created_at: now() };
  state.decisions.push(decision); refreshCounts(); persist(); return decision;
}

export async function mockRequest<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  settleJobs();
  const url = new URL(path, 'http://mock.local');
  const parts = url.pathname.split('/').filter(Boolean);
  const resource = parts[1], id = Number(parts[2]);
  const queryId = url.searchParams.get('query_id');
  if (queryId && ['records', 'export.csv'].includes(resource)) {
    requireItem(state.queries, query => query.id === Number(queryId), 'Query');
    if (resource === 'records' && parts[2] && !state.links[queryId]?.includes(id)) throw new Error('Record not found in this query');
  }
  let result: unknown;
  if (resource === 'health') result = { status: 'ok' };
  else if (resource === 'projects') {
    if (method === 'POST') {
      const title = String(object(body).title ?? '').trim();
      if (!title || title.length > 200) throw new Error('Enter a search title of 1 to 200 characters.');
      const project: Project = { id: idNext(state.projects), title, created_at: now() };
      state.projects.push(project); result = project;
    } else result = [...state.projects].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  }
  else if (resource === 'queries') {
    if (method === 'POST' && parts.length === 2) {
      const input = body as QueryInput;
      if (!input.text.trim() || !input.date_from || !input.date_to || input.date_from > input.date_to) throw new Error('Enter a query and a valid date range.');
      const projectId = input.project_id ?? 1;
      requireItem(state.projects, project => project.id === projectId, 'Search');
      const latest = [...state.queries].filter(query => query.project_id === projectId).sort((a, b) => b.version - a.version)[0];
      const parentId = Object.hasOwn(input, 'parent_id') ? input.parent_id ?? null : latest?.id ?? null;
      if (parentId !== null && requireItem(state.queries, query => query.id === parentId, 'Parent').project_id !== projectId) throw new Error('Parent query must belong to the same search');
      const query: QueryVersion = { ...input, id: idNext(state.queries), version: (latest?.version ?? 0) + 1, project_id: projectId, parent_id: parentId, hit_count: state.queries[0]?.hit_count ?? 42, translation: input.text, created_at: now(), status: 'saved', counts: { records: 0, include: 0, exclude: 0, maybe: 0 } };
      state.queries.push(query); result = { id: query.id, version: query.version, hit_count: query.hit_count, translation: query.translation };
    } else if (parts.length === 2) {
      const selected = url.searchParams.get('project_id');
      if (selected) requireItem(state.projects, project => project.id === Number(selected), 'Search');
      result = state.queries.filter(query => !selected || query.project_id === Number(selected)).sort((a,b) => a.version-b.version || a.id-b.id);
    }
    else {
      const query = requireItem(state.queries, query => query.id === id, 'Query');
      if (parts[3] === 'approve' && method === 'POST') { if (query.status === 'fetching') throw new Error('This query is already fetching.'); query.status = 'approved'; result = { id, status: 'approved' }; }
      else if (parts[3] === 'fetch' && method === 'POST') result = startJob(query, 'fetch');
      else result = query;
    }
  } else if (resource === 'pipeline') result = startJob(requireItem(state.queries, query => query.id === Number(url.searchParams.get('query_id')), 'Query'), 'pipeline');
  else if (resource === 'records') {
    if (parts[2]) result = recordView(requireItem(state.records, record => record.id === id, 'Record'));
    else {
      const queryId = url.searchParams.get('query_id'), label = url.searchParams.get('label');
      const records = state.records.map(recordView).filter(record => (!queryId || state.links[queryId]?.includes(record.id)) && (!label || record.label === label) && (url.searchParams.get('show_hidden') === 'true' || !record.hidden_duplicate));
      const limit = Math.max(1, Number(url.searchParams.get('limit') ?? 50)), offset = Math.max(0, Number(url.searchParams.get('offset') ?? 0));
      result = { items: records.slice(offset, offset + limit), total: records.length, limit, offset };
    }
  } else if (resource === 'runs') result = state.runs.filter(run => !url.searchParams.has('query_id') || run.query_id === Number(url.searchParams.get('query_id')));
  else if (resource === 'duplicates') result = state.duplicates;
  else if (resource === 'decisions') result = method === 'POST' ? decide(body as DecisionInput) : state.decisions;
  else if (resource === 'criteria') {
    if (method === 'PATCH') {
      const key = decodeURIComponent(parts[2]);
      decide({ entity_type: 'criterion', entity_id: key, action: 'toggle', new_value: body });
      result = requireItem(state.criteria, criterion => criterion.key === key, 'Criterion');
    } else result = state.criteria;
  } else if (resource === 'export.csv') {
    const fields = ['pmid', 'doi', 'title', 'abstract', 'year', 'journal', 'label', 'reason'] as const;
    const rows = state.records.map(recordView).filter(record => record.label === 'include' && !record.hidden_duplicate && (!queryId || state.links[queryId]?.includes(record.id)));
    const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const header = String(examples.endpoints.find(item => item.path.split('?')[0] === '/api/export.csv')!.response);
    return new Blob(['\ufeff', header, ...rows.map(row => fields.map(field => quote(row[field])).join(',') + '\r\n')], { type: 'text/csv;charset=utf-8' }) as T;
  } else throw new Error(`Mock endpoint not found: ${method} ${path}`);
  persist(); signal?.throwIfAborted(); return structuredClone(result) as T;
}
