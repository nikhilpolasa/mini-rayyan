import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import { Badge, LoadState, PageHeading, queryLink, useQueryContext } from './components';

export function showOffHoursAdvisory(hitCount: number, now: Date = new Date()): boolean {
  if (hitCount <= 200) return false;
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: '2-digit', hourCycle: 'h23' }).formatToParts(now);
  const day = parts.find(part => part.type === 'weekday')?.value;
  const hour = Number(parts.find(part => part.type === 'hour')?.value);
  return day !== 'Sat' && day !== 'Sun' && hour >= 5 && hour < 21;
}

export function DiffPage() {
  const queryId = useQueryContext();
  const query = useQuery({ queryKey: ['query', queryId], queryFn: ({ signal }) => api.query(queryId!, signal), enabled: !!queryId });
  const diff = useQuery({ queryKey: ['diff', queryId, query.data?.parent_id ?? null], queryFn: ({ signal }) => api.diff(queryId!, undefined, signal), enabled: !!queryId });
  const current = useQuery({ queryKey: ['records', queryId, 'diff-titles'], queryFn: ({ signal }) => api.records({ query_id: queryId, show_hidden: true, limit: 500 }, signal), enabled: !!queryId });
  const baseId = diff.data?.base_query_id;
  const base = useQuery({ queryKey: ['records', baseId ?? null, 'diff-titles'], queryFn: ({ signal }) => api.records({ query_id: baseId, show_hidden: true, limit: 500 }, signal), enabled: !!baseId });
  const titles = new Map([...(base.data?.items ?? []), ...(current.data?.items ?? [])].map(record => [record.id, record]));
  if (!queryId) return <p role="alert">Choose a query version first.</p>;
  return <><a className="back-link" href={queryLink('/queries', queryId)}>← Back to versions</a><PageHeading eyebrow="QUERY CHANGE" title={`Compare v${query.data?.version ?? ''} with parent`}>See what changed in the stored record sets.</PageHeading><LoadState pending={diff.isPending || current.isPending || base.isPending} error={diff.error ?? current.error ?? base.error} retry={() => { void diff.refetch(); void current.refetch(); void base.refetch(); }}/>
    {diff.data && <><div className="panel diff-counts"><strong>Added {diff.data.counts.added}</strong><strong>Removed {diff.data.counts.removed}</strong><strong>Common {diff.data.counts.common}</strong></div>
      {(['records_added', 'records_removed'] as const).map(kind => <section className="panel" key={kind}><h2>{kind === 'records_added' ? 'Added records' : 'Removed records'}</h2>{diff.data![kind].length ? diff.data![kind].map(id => { const record = titles.get(id), label = diff.data!.added_effective_labels[id]?.label ?? record?.label ?? 'maybe'; return <div className="member-row" key={id}><span>{record?.title ?? `Record #${id}`}</span><Badge label={label}/>{(diff.data!.common_with_human_decision.includes(id) || record?.source === 'human' || diff.data!.added_effective_labels[id]?.source === 'human') && <small>Human decision</small>}</div>; }) : <p>None</p>}</section>)}
      <section className="panel"><h2>Groups newly merged</h2>{diff.data.groups_newly_merged.length ? diff.data.groups_newly_merged.map(group => <div key={group.representative_record_id}><strong>Group #{group.representative_record_id}</strong><small> Based on groups {group.base_group_ids.join(', ')}</small>{group.member_ids.map(id => <div className="member-row" key={id}>{titles.get(id)?.title ?? `Record #${id}`}{diff.data!.common_with_human_decision.includes(id) && <small>Human decision</small>}</div>)}</div>) : <p>None</p>}</section>
      <section className="panel"><h2>Common records with human decisions</h2>{diff.data.common_with_human_decision.length ? diff.data.common_with_human_decision.map(id => <div className="member-row" key={id}>{titles.get(id)?.title ?? `Record #${id}`} <small>Human decision</small></div>) : <p>None</p>}</section></>}
  </>;
}

export function AsOfPage() {
  const queryId = useQueryContext();
  const query = useQuery({ queryKey: ['query', queryId], queryFn: ({ signal }) => api.query(queryId!, signal), enabled: !!queryId });
  const state = useQuery({ queryKey: ['as-of', queryId], queryFn: ({ signal }) => api.asOf(queryId!, signal), enabled: !!queryId });
  const records = useQuery({ queryKey: ['records', queryId, 'as-of-titles'], queryFn: ({ signal }) => api.records({ query_id: queryId, show_hidden: true, limit: 500 }, signal), enabled: !!queryId });
  const titles = new Map(records.data?.items.map(record => [record.id, record]));
  if (!queryId) return <p role="alert">Choose a query version first.</p>;
  return <><div className="notice" role="status">Viewing v{query.data?.version ?? '…'} as it was; nothing changed. <a href={queryLink('/queries', queryId)}>Return to versions</a></div><PageHeading eyebrow="STORED VERSION" title={`Version ${query.data?.version ?? ''}`}>Read-only record set and groups.</PageHeading><LoadState pending={state.isPending || records.isPending} error={state.error ?? records.error} retry={() => { void state.refetch(); void records.refetch(); }}/>
    {state.data && <><p className="muted"><small>State hash: <code>{state.data.state_hash}</code></small></p><section className="panel"><h2>Records ({state.data.record_ids.length})</h2>{state.data.record_ids.map(id => <div className="member-row" key={id}><span>{titles.get(id)?.title ?? `Record #${id}`}</span><Badge label={state.data!.effective_labels[id]?.label ?? 'maybe'}/></div>)}</section><section className="panel"><h2>Groups</h2>{state.data.groups.map(group => <div key={group.representative_record_id}><strong>Representative #{group.representative_record_id}</strong>{group.members.map(id => <div className="member-row" key={id}>{titles.get(id)?.title ?? `Record #${id}`} <small>{group.hidden.includes(id) ? 'Hidden duplicate' : 'Visible'}</small></div>)}</div>)}</section></>}
  </>;
}
