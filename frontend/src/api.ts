import { mockRequest } from './mocks/mock';
import type { Criterion, Decision, DecisionInput, Duplicates, Job, QueryCreated, QueryInput, QueryVersion, RecordDetail, RecordFilters, RecordPage, Run } from './types';

const baseUrl = () => (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '');
export const isMockMode = () => !baseUrl();

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = 'ApiError'; }
}

async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  if (isMockMode()) return mockRequest<T>(path, method, body, signal);
  let response: Response;
  try {
    response = await fetch(`${baseUrl()}${path}`, {
      method, signal,
      ...(body !== undefined ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('Could not reach the backend. Check the API URL, server and CORS configuration.', 0);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string | { msg: string }[] } | null;
    const detail = payload?.detail;
    throw new ApiError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : `Request failed (${response.status}).`, response.status);
  }
  if (path.split('?')[0] === '/api/export.csv') return await response.blob() as T;
  return await response.json() as T;
}

/** All backend requests go through this transport. API base is an origin, without /api. */
export const api = {
  health: (signal?: AbortSignal) => request<{ status: string }>('/api/health', 'GET', undefined, signal),
  queries: (signal?: AbortSignal) => request<QueryVersion[]>('/api/queries', 'GET', undefined, signal),
  query: (id: number, signal?: AbortSignal) => request<QueryVersion>(`/api/queries/${id}`, 'GET', undefined, signal),
  createQuery: (input: QueryInput) => request<QueryCreated>('/api/queries', 'POST', input),
  approve: (id: number) => request<{ id: number; status: 'approved' }>(`/api/queries/${id}/approve`, 'POST'),
  pull: (id: number) => request<Job>(`/api/queries/${id}/fetch`, 'POST'),
  pipeline: (id: number) => request<Job>(`/api/pipeline/run?query_id=${id}`, 'POST'),
  records: (filters: RecordFilters = {}, signal?: AbortSignal) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== undefined) params.set(key, String(value)); });
    return request<RecordPage>(`/api/records?${params}`, 'GET', undefined, signal);
  },
  record: (id: number, signal?: AbortSignal, queryId?: number) => request<RecordDetail>(`/api/records/${id}${queryId === undefined ? '' : `?query_id=${queryId}`}`, 'GET', undefined, signal),
  runs: (queryId?: number, signal?: AbortSignal) => request<Run[]>(`/api/runs${queryId ? `?query_id=${queryId}` : ''}`, 'GET', undefined, signal),
  duplicates: (signal?: AbortSignal) => request<Duplicates>('/api/duplicates', 'GET', undefined, signal),
  decide: (input: DecisionInput) => request<Decision>('/api/decisions', 'POST', input),
  decisions: (signal?: AbortSignal) => request<Decision[]>('/api/decisions', 'GET', undefined, signal),
  criteria: (signal?: AbortSignal) => request<Criterion[]>('/api/criteria', 'GET', undefined, signal),
  toggleCriterion: (key: string, active: boolean) => request<Criterion>(`/api/criteria/${encodeURIComponent(key)}`, 'PATCH', { active }),
  exportCsv: (queryId?: number) => request<Blob>(`/api/export.csv${queryId === undefined ? '' : `?query_id=${queryId}`}`),
};
