import { beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from './api';
import { RecordPageView, RecordsPage, ExportPage } from './pages';
import { resetMock } from './mocks/mock';

beforeEach(() => { resetMock(); vi.stubEnv('VITE_API_BASE_URL', ''); window.location.hash = ''; });

it('passes optional query context without changing omitted requests or CSV parsing', async () => {
  vi.stubEnv('VITE_API_BASE_URL', 'http://backend.test');
  const fetcher = vi.fn().mockImplementation(async (url: string) => new Response(url.includes('export.csv') ? 'pmid\r\n1\r\n' : '{}'));
  vi.stubGlobal('fetch', fetcher);
  await api.record(1);
  await api.record(1, undefined, 2);
  expect(await (await api.exportCsv(2)).text()).toBe('pmid\r\n1\r\n');
  expect(await (await api.exportCsv()).text()).toBe('pmid\r\n1\r\n');
  expect(fetcher.mock.calls.map(call => call[0])).toEqual([
    'http://backend.test/api/records/1', 'http://backend.test/api/records/1?query_id=2',
    'http://backend.test/api/export.csv?query_id=2', 'http://backend.test/api/export.csv',
  ]);
});

it('keeps detail caches separate when the same paper is opened in two query contexts', async () => {
  const original = await api.record(1);
  vi.spyOn(api, 'record').mockImplementation(async (_id, _signal, queryId) => ({ ...original, title: `Query ${queryId} paper`, label: queryId === 1 ? 'include' : 'maybe', pico_spans: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  window.location.hash = '#/records/1?query_id=1';
  const view = render(<QueryClientProvider client={client}><RecordPageView id={1}/></QueryClientProvider>);
  try {
    await screen.findByRole('heading', { name: 'Query 1 paper' });
    act(() => { window.location.hash = '#/records/1?query_id=2'; window.dispatchEvent(new HashChangeEvent('hashchange')); });
    await screen.findByRole('heading', { name: 'Query 2 paper' });
    expect(client.getQueryData(['record', 1, 1])).toMatchObject({ label: 'include' });
    expect(client.getQueryData(['record', 1, 2])).toMatchObject({ label: 'maybe' });
    expect(screen.getByRole('link', { name: /Back to records/ }).getAttribute('href')).toBe('#/records?query_id=2');
  } finally { view.unmount(); client.clear(); vi.restoreAllMocks(); }
});

it('retains the selected query in record links and export previews/downloads', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  window.location.hash = '#/records?query_id=1';
  const list = render(<QueryClientProvider client={client}><RecordsPage/></QueryClientProvider>);
  await screen.findByText('3 matching records');
  expect(screen.getByLabelText('Query version')).toHaveProperty('value', '1');
  expect(screen.getAllByRole('link').some(link => link.getAttribute('href') === '#/records/1?query_id=1')).toBe(true);
  list.unmount();
  const records = vi.spyOn(api, 'records');
  const exported = vi.spyOn(api, 'exportCsv');
  vi.stubGlobal('URL', class extends URL { static createObjectURL = () => 'blob:test'; static revokeObjectURL = vi.fn(); });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const view = render(<QueryClientProvider client={client}><ExportPage/></QueryClientProvider>);
  try {
    await screen.findByText('1 records, ready to export.');
    expect(records.mock.calls.some(([filters]) => filters?.query_id === 1)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Download included studies' }));
    await waitFor(() => expect(exported).toHaveBeenCalledWith(1));
  } finally { view.unmount(); client.clear(); vi.restoreAllMocks(); }
});
