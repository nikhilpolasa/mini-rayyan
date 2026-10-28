import { beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { QueriesPage } from './pages';
import { api } from './api';
import { resetMock } from './mocks/mock';

beforeEach(() => { resetMock(); vi.stubEnv('VITE_API_BASE_URL', ''); window.location.hash = ''; });
const input = { text: 'alpha[tiab]', date_from: '2020-01-01', date_to: '2026-01-01' };

it('numbers versions inside each mock thread and rejects cross-thread parents', async () => {
  const a = await api.createProject('Diabetes'), b = await api.createProject('Depression');
  const first = await api.createQuery({ ...input, project_id: a.id, parent_id: null });
  const second = await api.createQuery({ ...input, project_id: b.id, parent_id: null });
  expect(first.version).toBe(1); expect(second.version).toBe(1);
  expect((await api.createQuery({ ...input, project_id: a.id, parent_id: first.id })).version).toBe(2);
  await expect(api.createQuery({ ...input, project_id: a.id, parent_id: second.id })).rejects.toThrow('same search');
  expect((await api.queries(undefined, b.id)).map(query => query.id)).toEqual([second.id]);
  expect((await api.queries(undefined, 1))[0].version).toBe(1);
});

it('creates a sidebar thread, revises locally, and keeps histories/caches separate', async () => {
  const user = userEvent.setup();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><App/></QueryClientProvider>);
  try {
    await screen.findByRole('link', { name: 'Imported history (legacy)' });
    await user.click(screen.getByRole('button', { name: 'New search' }));
    await user.type(screen.getByLabelText('Search title'), 'Diabetes review');
    await user.click(screen.getByRole('button', { name: 'Create search' }));
    await waitFor(() => expect(window.location.hash).toContain('project_id=2'));
    await screen.findByText('Your first search starts here');
    await user.click(screen.getByLabelText('Search query')); await user.paste(input.text);
    await user.click(screen.getByRole('button', { name: /Save & check hits/ }));
    await screen.findByText('v1');
    await user.click(screen.getByRole('button', { name: 'Revise (new version)' }));
    await user.click(screen.getByLabelText('Search query')); await user.paste(input.text + ' AND placebo[tiab]');
    await user.click(screen.getByRole('button', { name: /Save & check hits/ }));
    await screen.findByText('v2');
    await screen.findByText('Based on v1');
    const scoped = client.getQueryData<unknown[]>(['queries', 2]);
    expect(scoped).toHaveLength(2);
    await user.click(screen.getByRole('link', { name: 'Imported history (legacy)' }));
    await waitFor(() => expect(window.location.hash).toContain('project_id=1'));
    await waitFor(() => expect(screen.queryByText('v2')).toBeNull());
    expect(client.getQueryData(['queries', 1])).toHaveLength(1);
    expect(client.getQueryData(['queries', 2])).toHaveLength(2);
    expect(screen.queryByText('Based on v1')).toBeNull();
    // Per-tab URL state selects another thread without a global current-project pointer.
    act(() => { window.location.hash = '#/queries?project_id=2'; window.dispatchEvent(new HashChangeEvent('hashchange')); });
    await screen.findByText('v2');
  } finally { view.unmount(); client.clear(); }
});

it('warns on sentence input without blocking save and does not warn on Boolean/tagged input', async () => {
  const user = userEvent.setup();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><QueriesPage/></QueryClientProvider>);
  try {
    const field = screen.getByLabelText('Search query');
    await user.type(field, 'In adults with diabetes does treatment improve symptoms');
    await screen.findByText(/PubMed needs keywords/);
    expect(screen.getByRole('button', { name: /Save & check hits/ })).toHaveProperty('disabled', false);
    await user.click(screen.getByRole('button', { name: /Save & check hits/ }));
    await screen.findByText('v2');
    await user.clear(field); await user.type(field, 'adult diabetes treatment outcome placebo symptoms scores AND trials');
    expect(screen.queryByText(/PubMed needs keywords/)).toBeNull();
    fireEvent.change(field, { target: { value: 'adult diabetes treatment outcome placebo symptoms scores[tiab]' } });
    expect(screen.queryByText(/PubMed needs keywords/)).toBeNull();
  } finally { view.unmount(); client.clear(); }
});
