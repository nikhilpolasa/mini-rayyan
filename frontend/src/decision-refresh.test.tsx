import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { api } from './api';
import { useAction } from './components';
import { mockRequest, resetMock } from './mocks/mock';
import type { DecisionInput } from './types';

// Begin list/log reads, save a decision, then deliver the older snapshots.
function Review({ input, recordId }: { input: DecisionInput; recordId: number }) {
  const records = useQuery({ queryKey: ['records', { show_hidden: true }], queryFn: ({ signal }) => api.records({ show_hidden: true }, signal) });
  const record = useQuery({ queryKey: ['record', recordId], queryFn: ({ signal }) => api.record(recordId, signal) });
  const log = useQuery({ queryKey: ['decisions'], queryFn: ({ signal }) => api.decisions(signal) });
  const duplicates = useQuery({ queryKey: ['duplicates'], queryFn: ({ signal }) => api.duplicates(signal) });
  const action = useAction(api.decide);
  return <>
    <button onClick={() => action.mutate(input)}>Save decision</button>
    {Object.entries({ records, record, log, duplicates }).map(([key, query]) => <output key={key} data-testid={key}>{JSON.stringify(query.data)}</output>)}
  </>;
}

beforeEach(() => { resetMock(); vi.stubEnv('VITE_API_BASE_URL', 'http://backend.test'); });

describe('decision refresh with older list/log requests in flight', () => {
  const cases: [string, number, DecisionInput][] = [
    ['label override', 3, { entity_type: 'record', entity_id: 3, action: 'set_label', new_value: { label: 'exclude' }, note: 'Checked' }],
    ['pair confirm', 4, { entity_type: 'pair', entity_id: '3:4', action: 'confirm', new_value: { status: 'confirmed' } }],
    ['pair reject', 4, { entity_type: 'pair', entity_id: '3:4', action: 'reject', new_value: { status: 'rejected' } }],
    ['PICO edit', 1, { entity_type: 'pico_span', entity_id: 1, action: 'add', new_value: { record_id: 1, label: 'P', start: 0, end: 6, text: 'Adults' } }],
  ];
  it.each(cases)('refreshes list, detail, duplicates and audit after %s', async (_, recordId, input) => {
    const pending: (() => void)[] = [];
    const held = new Set<string>();
    let writes = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      const parsed = new URL(url), path = parsed.pathname + parsed.search;
      const result = await mockRequest(path, init.method ?? 'GET', init.body ? JSON.parse(String(init.body)) : undefined);
      const response = new Response(JSON.stringify(result), { status: 200 });
      if (init.method === 'POST') writes++;
      if ((path.startsWith('/api/records?') || path === '/api/decisions') && init.method === 'GET' && !held.has(path)) {
        held.add(path);
        await new Promise<void>(resolve => pending.push(resolve));
      }
      return response;
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 5000 }, mutations: { retry: false } } });
    const view = render(<QueryClientProvider client={client}><Review input={input} recordId={recordId}/></QueryClientProvider>);
    try {
      await waitFor(() => expect(pending).toHaveLength(2));
      await waitFor(() => expect(screen.getByTestId('record').textContent).toContain('"id"'));
      fireEvent.click(screen.getByRole('button', { name: 'Save decision' }));
      await waitFor(() => expect(writes).toBe(1));
      pending.forEach(resolve => resolve());
      for (const [testId, path] of [
        ['log', '/api/decisions'], ['records', '/api/records?show_hidden=true'],
        ['record', `/api/records/${recordId}`], ['duplicates', '/api/duplicates'],
      ]) {
        const expected = await mockRequest(path);
        await waitFor(() => expect(JSON.parse(screen.getByTestId(testId).textContent!)).toEqual(expected));
      }
    } finally { pending.forEach(resolve => resolve()); view.unmount(); client.clear(); }
  });
});
