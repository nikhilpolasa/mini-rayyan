import { beforeEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from './api';
import { DiffPage, AsOfPage, showOffHoursAdvisory } from './level2';
import { DuplicatesPage } from './pages';
import { resetMock } from './mocks/mock';

beforeEach(() => { vi.stubEnv('VITE_API_BASE_URL', ''); resetMock(); window.location.hash = ''; vi.restoreAllMocks(); });
function view(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { ...render(<QueryClientProvider client={client}>{node}</QueryClientProvider>), client };
}

it('renders additions, removals, labels, merged titles, and human decisions', async () => {
  window.location.hash = '#/queries/diff?query_id=2';
  const original = await api.query(1);
  vi.spyOn(api, 'query').mockResolvedValue({ ...original, id: 2, version: 2, parent_id: 1 });
  vi.spyOn(api, 'diff').mockResolvedValue({ query_id: 2, base_query_id: 1, records_added: [3], records_removed: [1], records_common: [2], groups_newly_merged: [{ representative_record_id: 2, member_ids: [2, 3], base_group_ids: [2] }], counts: { added: 1, removed: 1, common: 1, groups_newly_merged: 1 }, added_effective_labels: { 3: { label: 'include', reason: 'matches', criterion: '', source: 'machine' } }, common_with_human_decision: [2] });
  const originalRecords = api.records;
  vi.spyOn(api, 'records').mockImplementation(async (filters, signal) => originalRecords({ ...filters, query_id: undefined }, signal));
  const page = view(<DiffPage/>);
  try {
    await screen.findByText('Added 1');
    expect(screen.getByText('Removed 1')).toBeTruthy();
    expect(screen.getByText('Common 1')).toBeTruthy();
    expect(screen.getByText('Groups newly merged')).toBeTruthy();
    expect(screen.getAllByText(/Human decision/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Fictional candidate 3/).length).toBeGreaterThan(0);
  } finally { page.unmount(); page.client.clear(); }
});

it('shows a read-only as-of banner, return link, groups and state hash', async () => {
  window.location.hash = '#/queries/as-of?query_id=1';
  const page = view(<AsOfPage/>);
  try {
    await screen.findByText(/Viewing v1 as it was; nothing changed/);
    expect(screen.getByRole('link', { name: 'Return to versions' })).toBeTruthy();
    await screen.findByText(/State hash:/);
    expect(screen.getByText('Groups')).toBeTruthy();
  } finally { page.unmount(); page.client.clear(); }
});

it('requires an explicit group resolution for different human labels', async () => {
  await api.decide({ entity_type: 'record', entity_id: 1, action: 'set_label', new_value: { label: 'include' } });
  await api.decide({ entity_type: 'record', entity_id: 2, action: 'set_label', new_value: { label: 'exclude' } });
  const page = view(<DuplicatesPage/>);
  try {
    await screen.findByText('Conflict in group #1');
    expect(screen.getByText(/different reviewer labels/)).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Resolve group label'), 'include');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve conflict' }));
    await waitFor(() => expect(screen.queryByText('Conflict in group #1')).toBeNull());
    expect((await api.decisions()).at(-1)?.entity_type).toBe('group');
  } finally { page.unmount(); page.client.clear(); }
});

it('uses New York local weekday hours including daylight saving time', () => {
  expect(showOffHoursAdvisory(200, new Date('2026-10-28T16:00:00Z'))).toBe(false);
  expect(showOffHoursAdvisory(201, new Date('2026-10-28T16:00:00Z'))).toBe(true);
  expect(showOffHoursAdvisory(201, new Date('2026-10-28T01:00:00Z'))).toBe(false);
  expect(showOffHoursAdvisory(201, new Date('2026-10-31T16:00:00Z'))).toBe(false);
  expect(showOffHoursAdvisory(201, new Date('2026-01-12T16:00:00Z'))).toBe(true);
});
