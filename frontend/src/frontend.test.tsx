import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from './api';
import { PicoAbstract } from './components';
import { mockRequest, resetMock } from './mocks/mock';
import { CriteriaPage, DuplicatesPage, QueriesPage, RecordPageView, RecordsPage, DecisionsPage, ExportPage } from './pages';
import App from './App';
import type { PicoSpan } from './types';

beforeEach(() => { vi.stubEnv('VITE_API_BASE_URL', ''); resetMock(); window.location.hash = ''; });
function view(component: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{component}</QueryClientProvider>);
}
async function fetchedQuery() {
  await api.approve(1); await api.pull(1);
  const time = Date.now(); vi.spyOn(Date, 'now').mockReturnValue(time + 2000);
  await api.queries(); vi.restoreAllMocks();
}

describe('safe PICO rendering', () => {
  it('escapes hostile HTML and matches Unicode code point offsets with overlapping spans', () => {
    const text = '🧪Adults <img src=x onerror=alert(1)> & text';
    const span = (id: number, start: number, end: number, label: PicoSpan['label']): PicoSpan => ({ id, start, end, label, text: Array.from(text).slice(start, end).join(''), source: 'human', pico_version: 'human', rule_set_version: 'human', run_id: null });
    const html = renderToStaticMarkup(<PicoAbstract text={text} spans={[span(1, 1, 7, 'P'), span(2, 1, 4, 'I'), { ...span(3, 2, 5, 'O'), text: 'invalid' }]}/>);
    expect(html).not.toContain('<img'); expect(html).toContain('&lt;img'); expect(html).toContain('pico-P'); expect(html).toContain('Population + Intervention');
    const { container } = render(<PicoAbstract text={text} spans={[span(1, 1, 7, 'P')]}/>);
    expect(container.textContent).toBe(text); expect(container.querySelector('mark')?.textContent).toBe('Adults'); expect(container.querySelector('img')).toBeNull();
  });
});

describe('mock API contracts and state', () => {
  it('creates immutable versions, requires approval, polls jobs and keeps decisions after a rerun', async () => {
    const original = await api.query(1);
    const created = await api.createQuery({ text: 'new[tiab] AND question[tiab]', date_from: '2020-01-01', date_to: '2026-10-27' });
    expect(created.version).toBe(2); expect((await api.query(1)).text).toBe(original.text);
    await expect(api.pull(created.id)).rejects.toThrow('Approve');
    await fetchedQuery();
    expect((await api.query(1)).status).toBe('fetched'); expect((await api.runs())[0].status).toBe('completed');
    const before = await api.decisions(); await api.pipeline(1);
    expect((await api.decisions()).length).toBe(before.length);
  });
  it('filters, paginates, hides duplicates and keeps overrides append-only', async () => {
    expect((await api.records({ show_hidden: true })).total).toBe(4);
    expect((await api.records({ show_hidden: false })).total).toBe(3);
    expect((await api.records({ show_hidden: true, limit: 2, offset: 2 })).items.map(record => record.id)).toEqual([3, 4]);
    const before = await api.decisions();
    await api.decide({ entity_type: 'record', entity_id: 3, action: 'set_label', new_value: { label: 'exclude' }, note: 'Not eligible' });
    expect((await api.records({ label: 'exclude' })).total).toBe(1);
    await api.decide({ entity_type: 'record', entity_id: 3, action: 'undo', new_value: null });
    expect((await api.record(3)).label).toBe('maybe'); expect((await api.decisions()).slice(0, before.length)).toEqual(before);
    expect((await api.decisions()).length).toBe(before.length + 2);
  });
  it('records criteria changes and resolves uncertain pairs without deleting records', async () => {
    await api.toggleCriterion('non_human', false);
    expect((await api.criteria())[0].active).toBe(false);
    await api.decide({ entity_type: 'pair', entity_id: '3:4', action: 'confirm', new_value: { status: 'confirmed' } });
    expect((await api.duplicates()).uncertain_pairs.length).toBe(0);
    expect((await api.records()).total).toBe(2); expect((await api.records({ show_hidden: true })).total).toBe(4);
    expect((await api.decisions()).at(-1)?.entity_type).toBe('pair');
  });
  it('exports included records as a CSV Blob with quoted abstract text', async () => {
    const blob = await api.exportCsv();
    const text = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob); });
    expect(text).toContain('pmid,doi,title,abstract,year,journal,label,reason'); expect(text).toContain('"DEMO-0001"'); expect(text).toContain('Adults were assigned'); expect(text).not.toContain('DEMO-0002');
  });
  it('supports human PICO add, relabel, remove and undo', async () => {
    await api.decide({ entity_type: 'pico_span', entity_id: 1, action: 'add', new_value: { record_id: 1, label: 'P', start: 0, end: 6, text: 'Adults' } });
    const span = (await api.record(1)).pico_spans[0];
    await api.decide({ entity_type: 'pico_span', entity_id: span.id, action: 'relabel', new_value: { label: 'I' } });
    expect((await api.record(1)).pico_spans[0].label).toBe('I');
    await api.decide({ entity_type: 'pico_span', entity_id: span.id, action: 'remove', new_value: null });
    expect((await api.record(1)).pico_spans.length).toBe(0);
    await api.decide({ entity_type: 'pico_span', entity_id: span.id, action: 'undo', new_value: null });
    expect((await api.record(1)).pico_spans[0].label).toBe('I');
  });
  it('adds multiple PICO spans without replacing earlier annotations and undoes only the latest addition', async () => {
    await api.decide({ entity_type: 'pico_span', entity_id: 1, action: 'add', new_value: { record_id: 1, label: 'P', start: 0, end: 6, text: 'Adults' } });
    await api.decide({ entity_type: 'pico_span', entity_id: 1, action: 'add', new_value: { record_id: 1, label: 'I', start: 24, end: 32, text: 'exercise' } });
    expect((await api.record(1)).pico_spans.length).toBe(2);
    await api.decide({ entity_type: 'pico_span', entity_id: 1, action: 'undo', new_value: null });
    expect((await api.record(1)).pico_spans.map(span => span.label)).toEqual(['P']);
  });
});

describe('live API transport', () => {
  it('uses VITE_API_BASE_URL, encodes filters and sends exact decision payloads', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000/');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.records({ query_id: 2, label: 'exclude', show_hidden: true, limit: 50, offset: 100 });
    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/records?query_id=2&label=exclude&show_hidden=true&limit=50&offset=100');
    const input = { entity_type: 'record' as const, entity_id: 1, action: 'set_label', new_value: { label: 'include' }, note: 'Checked' };
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
    await api.decide(input);
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify(input));
  });
  it('shows backend and network errors without silently switching to mock data', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Approve the query before fetching' }), { status: 409 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.pull(1)).rejects.toThrow('Approve the query before fetching');
    fetchMock.mockRejectedValueOnce(new TypeError('offline'));
    await expect(api.queries()).rejects.toThrow('Could not reach the backend');
  });
});

describe('review pages', () => {
  it('submits a query and shows the new version and translation', async () => {
    const user = userEvent.setup(); view(<QueriesPage/>);
    await screen.findByText('Search history');
    await user.type(screen.getByLabelText('Search query'), 'walking[tiab] AND sleep[tiab]');
    await user.click(screen.getByRole('button', { name: /Save & check hits/ }));
    await screen.findByText('v2');
    expect((await api.queries()).length).toBe(2); expect(screen.getAllByText('PubMed querytranslation').length).toBe(2);
  });
  it('filters records and opens hidden duplicates', async () => {
    const user = userEvent.setup(); view(<RecordsPage/>);
    await screen.findByText('3 matching records');
    await user.click(screen.getByLabelText('Show hidden duplicates'));
    await screen.findByText('4 matching records');
    await user.selectOptions(screen.getByLabelText('Screening label'), 'include');
    await screen.findByText('1 matching records');
  });
  it('submits record overrides, notes and undo to the decision log', async () => {
    const user = userEvent.setup(); view(<RecordPageView id={3}/>);
    const note = await screen.findByLabelText(/Reviewer note/);
    await user.type(note, 'Reviewed metadata');
    await user.click(screen.getByRole('button', { name: 'Exclude' }));
    await waitFor(async () => expect((await api.record(3)).label).toBe('exclude'));
    expect((await api.decisions()).at(-1)?.note).toBe('Reviewed metadata');
    await user.click(screen.getByRole('button', { name: /Undo latest record decision/ }));
    await waitFor(async () => expect((await api.record(3)).label).toBe('maybe'));
  });
  it('confirms duplicate pairs and toggles criteria', async () => {
    const user = userEvent.setup(); const pairView = view(<DuplicatesPage/>);
    await user.click(await screen.findByRole('button', { name: 'Confirm duplicate' }));
    await screen.findByText('No uncertain pairs waiting');
    pairView.unmount(); view(<CriteriaPage/>);
    const toggle = await screen.findByRole('switch', { name: 'Enable Non-human studies' });
    await user.click(toggle);
    await waitFor(async () => expect((await api.criteria())[0].active).toBe(false));
  });
  it('renders audit history and CSV download controls', async () => {
    const log = view(<DecisionsPage/>);
    await screen.findByText('1 logged decisions');
    expect(screen.getByRole('button', { name: 'Undo latest' })).toBeTruthy();
    log.unmount(); view(<ExportPage/>);
    await screen.findByText('1 records, ready to export.');
    const create = vi.fn().mockReturnValue('blob:unit-test');
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = vi.fn(); });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    await userEvent.click(screen.getByRole('button', { name: 'Download included studies' }));
    await screen.findByText('CSV download started.'); expect(create).toHaveBeenCalled(); vi.restoreAllMocks();
  });
  it('shows all navigation destinations and the NCBI disclaimer', async () => {
    view(<App/>);
    expect(screen.getByRole('navigation', { name: 'Main navigation' }).querySelectorAll('a').length).toBe(6);
    expect(screen.getByRole('link', { name: 'NCBI disclaimer ↗' }).getAttribute('href')).toBe('https://www.ncbi.nlm.nih.gov/home/about/policies/');
    expect(screen.getByText('Mock workspace')).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: 'Records' }));
    await screen.findByText('Every record deserves a clear decision.');
  });
});
