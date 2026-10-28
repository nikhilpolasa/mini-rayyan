import { useEffect, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, isMockMode } from './api';
import { Badge, Empty, Feedback, Icon, LoadState, PageHeading, PicoAbstract, dateText, picoLabels, useAction, useQueryContext, useProjectContext, queryLink } from './components';
import type { DecisionInput, Label, PicoSpan, QueryInput, QueryVersion } from './types';

export function QueriesPage() {
  const projectId = useProjectContext();
  const queryClient = useQueryClient();
  const queries = useQuery({ queryKey: ['queries', projectId], queryFn: ({ signal }) => api.queries(signal, projectId), refetchInterval: query => query.state.data?.some(item => item.status === 'fetching') ? 1200 : false });
  const runs = useQuery({ queryKey: ['runs', projectId], queryFn: ({ signal }) => api.runs(undefined, signal), refetchInterval: query => query.state.data?.some(item => ['queued', 'running'].includes(item.status)) ? 1200 : false });
  const [form, setForm] = useState<QueryInput>({ text: '', date_from: '2016-01-01', date_to: new Date().toISOString().slice(0, 10) });
  const [formError, setFormError] = useState('');
  const [parentId, setParentId] = useState<number | null>(null);
  const [pullLimits, setPullLimits] = useState<Record<number, string>>({});
  const sentenceWarning = form.text.trim().split(/\s+/).length > 6 && !/\[[^\]]+\]/.test(form.text) && !/\b(?:AND|OR|NOT)\b/i.test(form.text);
  const save = useAction(api.createQuery);
  const action = useAction(async ({ type, id }: { type: 'approve' | 'pull' | 'pipeline'; id: number }) => type === 'pull' ? api.pull(id, pullLimits[id] ? Number(pullLimits[id]) : undefined) : api[type](id));
  const projectRuns = runs.data?.filter(run => queries.data?.some(query => query.id === run.query_id));
  const completed = projectRuns?.filter(run => ['completed', 'failed'].includes(run.status)).map(run => `${run.id}:${run.status}`).join(',');
  useEffect(() => { if (completed) void queryClient.invalidateQueries({ queryKey: ['queries', projectId] }); }, [completed, queryClient]);

  function submit(event: FormEvent) {
    event.preventDefault(); setFormError('');
    if (!form.text.trim()) { setFormError('Enter a search query.'); return; }
    if (form.date_to < form.date_from) { setFormError('The end date must be on or after the start date.'); return; }
    save.mutate({ ...form, project_id: projectId, parent_id: parentId }, { onSuccess: created => setParentId(created.id) });
  }
  const versions = queries.data ?? [];
  const running = projectRuns?.some(run => ['queued', 'running'].includes(run.status));
  return <>
    <PageHeading eyebrow="01 / FIND THE EVIDENCE" title="A good review starts with a question.">Search PubMed, compare versions, and bring the right evidence into focus.</PageHeading>
    <div className="query-layout">
      <section className="panel search-panel"><div className="section-title"><span className="icon-tile"><Icon name="search"/></span><div><h2>{parentId ? 'Revise query' : 'Search query'}</h2><p>Your question, in PubMed’s language.</p></div></div>
        <form onSubmit={submit}><label htmlFor="query-text">Search query</label><textarea id="query-text" required rows={4} value={form.text} onChange={event => setForm({ ...form, text: event.target.value })} placeholder={'e.g. intervention[tiab] AND outcome[tiab]'}/><p className="field-hint">Combine concepts with AND, OR and NOT. PubMed field tags are supported.</p>
          <div className="form-row"><div><label htmlFor="date-from">Published from</label><input id="date-from" type="date" required value={form.date_from} onChange={event => setForm({ ...form, date_from: event.target.value })}/></div><div><label htmlFor="date-to">Published to</label><input id="date-to" type="date" required min={form.date_from} value={form.date_to} onChange={event => setForm({ ...form, date_to: event.target.value })}/></div></div>
          {sentenceWarning && <p className="notice" role="status">PubMed needs keywords or a Boolean query rather than a full question. You can still continue.</p>}
          {formError && <p role="alert" className="notice notice-error">{formError}</p>}<Feedback action={save} success={save.data ? `Saved as version ${save.data.version} · ${save.data.hit_count.toLocaleString()} PubMed hits${isMockMode() ? ' (example count)' : ''}.` : undefined}/>
          <div className="form-bottom"><span><Icon name="history" size={15}/> Every search is a new version.</span><button className="btn btn-primary" disabled={save.isPending}>{save.isPending ? <span className="spinner"/> : <Icon name="plus" size={17}/>} {save.isPending ? 'Searching PubMed…' : 'Save & check hits'}</button></div>
        </form>
      </section>
      <aside className="guide-panel"><p className="eyebrow">A CLEAR PATH FORWARD</p><h2>From question<br/>to evidence.</h2><ol className="workflow"><li><span>1</span><div><strong>Search & refine</strong><p>Explore a query. Keep its history.</p></div></li><li><span>2</span><div><strong>Approve & pull</strong><p>Choose which results to bring in.</p></div></li><li><span>3</span><div><strong>Screen & review</strong><p>Let rules assist. Make the final call.</p></div></li></ol><div className="guide-note"><Icon name="leaf" size={21}/><p>Nothing gets lost.<br/><strong>Every decision has a history.</strong></p></div></aside>
    </div>
    <div className="section-heading"><div><h2>Search history <span className="count-pill">{versions.length}</span></h2><p>Saved versions stay intact as your question evolves.</p></div>{running && <span className="running-label" role="status"><span className="spinner"/> Processing · updates automatically</span>}</div>
    <LoadState pending={queries.isPending || runs.isPending} error={queries.error ?? runs.error} retry={() => { void queries.refetch(); void runs.refetch(); }}/><Feedback action={action} success={action.data ? 'Request accepted. Status updates automatically.' : undefined}/>
    {!queries.isPending && !queries.error && !versions.length && <section className="panel"><Empty title="Your first search starts here">Save a query above to see its hit count and PubMed translation.</Empty></section>}
    <div className="version-list">{[...versions].reverse().map(query => {
      const latestRun = [...(projectRuns ?? [])].reverse().find(run => run.query_id === query.id);
      const parent = versions.find(version => version.id === query.parent_id);
      const busy = query.status === 'fetching' || latestRun && ['running', 'queued'].includes(latestRun.status);
      return <article className="panel version-card" key={query.id}><div className="version-top"><div className="version-meta"><span className="version-number">v{query.version}</span><span className={`status status-${query.status}`}>{query.status}</span><span className="muted">{dateText(query.created_at)}</span></div><div className="hit-count"><strong>{query.hit_count.toLocaleString()}</strong> hits <span>on PubMed{isMockMode() ? ' · example' : ''}</span></div></div>
        <h3 className="query-expression">{query.text}</h3><div className="version-subline"><span>{query.date_from} → {query.date_to}</span><span>{query.counts.records ?? 0} linked records</span>{parent && <span>Based on v{parent.version}</span>}</div>
        <details className="translation"><summary>PubMed querytranslation</summary><code>{query.translation || 'No translation returned.'}</code></details>
        {busy && <div className="job-progress" role="status"><div className="progress-track"><div/></div><p>{latestRun?.step === 'pipeline' ? 'Deduplicating → screening → tagging PICO' : 'Pulling abstracts in the background'} · elapsed time and counts appear below.</p></div>}
        {latestRun?.status === 'failed' && <p className="notice notice-error" role="alert">The {latestRun.step} job failed. For a fetch failure, approve this query again and retry. Check source availability if the problem continues.</p>}
        {latestRun?.status === 'completed' && <p className="run-summary"><Icon name="check" size={15}/>{latestRun.step} completed{latestRun.counts.seconds !== undefined ? ` in ${latestRun.counts.seconds}s` : ''}{latestRun.counts.records_in !== undefined ? ` · ${latestRun.counts.records_in} records processed` : ''}</p>}
        <div className="version-actions"><button className="btn btn-small" disabled={action.isPending || !!busy || query.status === 'approved' || query.status === 'fetched'} onClick={() => action.mutate({ type: 'approve', id: query.id })}><Icon name="check" size={15}/> Approve</button><label htmlFor={`pull-limit-${query.id}`}>Pull up to</label><select id={`pull-limit-${query.id}`} value={pullLimits[query.id] ?? ''} onChange={event => setPullLimits({ ...pullLimits, [query.id]: event.target.value })} disabled={action.isPending || !!busy}><option value="">Server default</option>{[10, 25, 50, 100, 250, 500].map(count => <option key={count} value={count}>{count} records</option>)}</select><button className="btn btn-small btn-primary" disabled={action.isPending || !!busy || !['approved', 'fetched'].includes(query.status)} onClick={() => action.mutate({ type: 'pull', id: query.id })}><Icon name="download" size={15}/> Pull abstracts</button><button className="btn btn-small" disabled={action.isPending || !!busy || query.status !== 'fetched'} onClick={() => action.mutate({ type: 'pipeline', id: query.id })}>Run pipeline <Icon name="arrow" size={15}/></button><button className="text-button clone-button" onClick={() => { setForm({ text: query.text, date_from: query.date_from, date_to: query.date_to }); setParentId(query.id); document.getElementById('query-text')?.focus(); }}>Revise (new version)</button></div>
      </article>;
    })}</div>
  </>;
}

export function RecordsPage() {
  const projectId = useProjectContext();
  const queryId = useQueryContext();
  const [label, setLabel] = useState(''), [hidden, setHidden] = useState(false), [limit, setLimit] = useState(25), [offset, setOffset] = useState(0);
  const queries = useQuery({ queryKey: ['queries', projectId], queryFn: ({ signal }) => api.queries(signal, projectId) });
  const filters = { query_id: queryId, label: label ? label as Label : undefined, show_hidden: hidden, limit, offset };
  const records = useQuery({ queryKey: ['records', projectId, filters], queryFn: ({ signal }) => api.records(filters, signal), refetchInterval: 5000 });
  function filter(action: () => void) { action(); setOffset(0); }
  return <><PageHeading eyebrow="02 / SCREEN & REVIEW" title="Every record deserves a clear decision.">Read the evidence, understand the reason, and keep the final say.</PageHeading>
    <section className="panel"><div className="filter-bar"><div><label htmlFor="version-filter">Query version</label><select id="version-filter" value={queryId ?? ''} onChange={event => filter(() => { window.location.hash = queryLink('/records', event.target.value ? Number(event.target.value) : undefined, projectId); })}><option value="">All stored records (shared)</option>{queries.data?.map(query => <option key={query.id} value={query.id}>Version {query.version} · {query.text.slice(0, 38)}</option>)}</select></div><div><label htmlFor="label-filter">Screening label</label><select id="label-filter" value={label} onChange={event => filter(() => setLabel(event.target.value))}><option value="">All labels</option><option value="include">Include</option><option value="exclude">Exclude</option><option value="maybe">Maybe</option></select></div><label className="check-label"><input type="checkbox" checked={hidden} onChange={event => filter(() => setHidden(event.target.checked))}/> Show hidden duplicates</label></div>
      <LoadState pending={records.isPending} error={records.error ?? queries.error} retry={() => { void records.refetch(); void queries.refetch(); }}/>
      {records.data && <><div className="table-caption"><strong>{records.data.total} matching records</strong><span>Labels reflect the latest human override.</span></div><div className="table-scroll"><table><thead><tr><th>STUDY</th><th>SCREENING</th><th>REASON & SOURCE</th><th><span className="sr-only">Open record</span></th></tr></thead><tbody>{records.data.items.map(record => <tr key={record.id} className={record.hidden_duplicate ? 'hidden-record' : ''}><td><a className="record-title" href={queryLink(`/records/${record.id}`, queryId, projectId)}>{record.title || 'Untitled record'}</a><div className="record-meta">{record.journal ?? 'Journal unavailable'} · {record.year ?? 'Year unavailable'}<br/><span>PMID {record.pmid}</span>{record.hidden_duplicate && <span className="hidden-pill">Hidden duplicate</span>}</div></td><td><Badge label={record.label}/></td><td><p className="reason-text">{record.reason || 'No reason supplied.'}</p><span className={`source source-${record.source}`}>{record.source === 'human' ? 'Reviewer override' : 'Machine result'}</span>{record.criterion && <small className="criterion-key">{record.criterion}</small>}</td><td><a className="row-open" href={queryLink(`/records/${record.id}`, queryId, projectId)} aria-label={`Review ${record.title}`}><Icon name="arrow"/></a></td></tr>)}</tbody></table></div>
        {!records.data.items.length && <Empty title="No records match these filters">Try another label or query version, or show hidden duplicates.</Empty>}
        <div className="pagination"><span>{records.data.total ? `${offset + 1}–${Math.min(offset + limit, records.data.total)}` : '0'} of {records.data.total}</span><div><label htmlFor="page-size">Per page</label><select id="page-size" value={limit} onChange={event => filter(() => setLimit(Number(event.target.value)))}>{[10, 25, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}</select><button className="btn btn-small" disabled={offset === 0 || records.isFetching} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button><button className="btn btn-small" disabled={offset + limit >= records.data.total || records.isFetching} onClick={() => setOffset(offset + limit)}>Next</button></div></div>
      </>}
    </section></>;
}

export function RecordPageView({ id }: { id: number }) {
  const projectId = useProjectContext();
  const queryId = useQueryContext();
  const record = useQuery({ queryKey: ['record', projectId, id, queryId ?? null], queryFn: ({ signal }) => api.record(id, signal, queryId) });
  const action = useAction(api.decide);
  const [note, setNote] = useState('');
  const [tag, setTag] = useState<{ label: PicoSpan['label']; start: number; end: number }>({ label: 'P', start: 0, end: 6 });
  const data = record.data;
  const chars = Array.from(data?.abstract ?? '');
  const tagValid = Number.isInteger(tag.start) && Number.isInteger(tag.end) && tag.start >= 0 && tag.end > tag.start && tag.end <= chars.length;
  const latest = data?.decisions.some(decision => decision.entity_type === 'record' && String(decision.entity_id) === String(id));
  function decide(input: DecisionInput) { action.mutate(input, { onSuccess: () => setNote('') }); }
  return <><a className="back-link" href={queryLink('/records', queryId, projectId)}>← Back to records</a><LoadState pending={record.isPending} error={record.error} retry={record.refetch}/>
    {data && <><PageHeading eyebrow={`RECORD ${data.id} / PMID ${data.pmid}`} title={data.title || 'Untitled record'}>{data.authors.join(', ') || 'Authors unavailable'} · {data.journal ?? 'Journal unavailable'} · {data.year ?? 'Year unavailable'}</PageHeading>
      <div className="detail-layout"><div><section className="panel abstract-panel"><div className="section-heading compact"><h2>Abstract</h2><div className="pico-legend">{Object.entries(picoLabels).map(([key, value]) => <span key={key}><i className={`pico-${key}`}/>{value}</span>)}</div></div>{data.abstract ? <PicoAbstract text={data.abstract} spans={data.pico_spans}/> : <Empty title="No abstract available">Review the available metadata before making a decision.</Empty>}
        <div className="metadata-row"><span>Language: {data.language ?? 'Unknown'}</span><span>{data.pub_types.join(' · ') || 'Publication type unavailable'}</span></div>
        {data.mesh.length > 0 && <div className="tag-list">{data.mesh.map((mesh, index) => <span key={`${mesh}-${index}`}>{mesh}</span>)}</div>}
      </section>
      <section className="panel pico-editor"><div className="section-heading compact"><div><h2>PICO annotations <span className="count-pill">{data.pico_spans.length}</span></h2><p>Offsets reference the exact stored abstract.</p></div></div>
        {data.pico_spans.map(span => <div className="span-row" key={span.id}><span className={`pico-token pico-${span.label}`}>{span.label}</span><div><strong>{span.text}</strong><small>{span.start}–{span.end} · {span.source}</small></div><select aria-label={`Relabel annotation ${span.id}`} value={span.label} disabled={action.isPending} onChange={event => decide({ entity_type: 'pico_span', entity_id: span.id, action: 'relabel', new_value: { label: event.target.value }, note })}>{Object.entries(picoLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select><button className="icon-button" aria-label={`Remove annotation ${span.id}`} disabled={action.isPending} onClick={() => decide({ entity_type: 'pico_span', entity_id: span.id, action: 'remove', new_value: null, note })}><Icon name="close" size={17}/></button></div>)}
        {!data.pico_spans.length && <p className="muted">No PICO tags yet. You can add a reviewer annotation below.</p>}
        <details className="add-tag"><summary>Add a PICO annotation</summary><form onSubmit={event => { event.preventDefault(); if (tagValid) decide({ entity_type: 'pico_span', entity_id: id, action: 'add', new_value: { record_id: id, ...tag, text: chars.slice(tag.start, tag.end).join('') }, note }); }}><div className="tag-form"><div><label htmlFor="pico-label">Label</label><select id="pico-label" value={tag.label} onChange={event => setTag({ ...tag, label: event.target.value as PicoSpan['label'] })}>{Object.entries(picoLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></div><div><label htmlFor="pico-start">Start</label><input id="pico-start" type="number" min="0" required value={Number.isNaN(tag.start) ? '' : tag.start} onChange={event => setTag({ ...tag, start: event.target.valueAsNumber })}/></div><div><label htmlFor="pico-end">End (exclusive)</label><input id="pico-end" type="number" min="1" max={chars.length} required value={Number.isNaN(tag.end) ? '' : tag.end} onChange={event => setTag({ ...tag, end: event.target.valueAsNumber })}/></div></div><p className="tag-preview">{tagValid ? `Selected text: “${chars.slice(tag.start, tag.end).join('')}”` : `Use valid offsets between 0 and ${chars.length}.`}</p><button className="btn btn-small" disabled={!tagValid || action.isPending}><Icon name="plus" size={15}/> Add annotation</button></form></details>
      </section>
      <section className="panel provenance"><h2>Record history</h2><p>Found by {data.query_versions.map(query => `v${query.version}`).join(', ') || 'no linked query'} · fetched {dateText(data.fetched_at)}</p>{data.group && <p>Duplicate group #{data.group.id} · representative #{data.group.representative_record_id}{data.hidden_duplicate ? ' · this record is hidden' : ''}</p>}{data.decisions.length ? data.decisions.map(decision => <div className="history-row" key={decision.id}><strong>{decision.action.replaceAll('_', ' ')}</strong><span>{decision.note || JSON.stringify(decision.new_value)}</span><small>{dateText(decision.created_at)} · {decision.actor}</small></div>) : <p className="muted">No reviewer changes yet.</p>}</section></div>
      <aside className="panel reviewer-panel"><p className="eyebrow">YOUR REVIEW</p><h2>The final say is yours.</h2><div className="current-label"><Badge label={data.label}/><span className={`source source-${data.source}`}>{data.source === 'human' ? 'Reviewer override' : 'Machine result'}</span></div><p className="current-reason">{data.reason || 'No reason supplied.'}</p>{data.hidden_duplicate && <p className="notice">This record is a hidden duplicate. Your review remains in its history.</p>}
        <label htmlFor="review-note">Reviewer note <span className="optional">(optional)</span></label><textarea id="review-note" rows={4} value={note} onChange={event => setNote(event.target.value)} placeholder="What informed your decision?"/>
        <div className="override-buttons">{(['include', 'exclude', 'maybe'] as Label[]).map(label => <button className={`btn btn-label-${label}`} disabled={action.isPending} key={label} onClick={() => decide({ entity_type: 'record', entity_id: id, action: 'set_label', new_value: { label }, note })}>{label === 'include' ? <Icon name="check" size={16}/> : label === 'exclude' ? <Icon name="close" size={16}/> : <span>?</span>}{label[0].toUpperCase() + label.slice(1)}</button>)}</div><button className="btn full-width" disabled={action.isPending || !note.trim()} onClick={() => decide({ entity_type: 'record', entity_id: id, action: 'note', new_value: null, note })}>Save note only</button><button className="text-button undo-button" disabled={action.isPending || !latest} onClick={() => decide({ entity_type: 'record', entity_id: id, action: 'undo', new_value: null, note })}><Icon name="history" size={15}/> Undo latest record decision</button><Feedback action={action} success="Reviewer change saved to the decision log."/>
        <p className="review-assurance"><Icon name="history" size={16}/> Changes are logged. Machine reruns preserve your work.</p>
      </aside></div>
    </>}
  </>;
}

export function DuplicatesPage() {
  const projectId = useProjectContext();
  const duplicates = useQuery({ queryKey: ['duplicates', projectId], queryFn: ({ signal }) => api.duplicates(signal) });
  const action = useAction(api.decide);
  const [note, setNote] = useState('');
  const data = duplicates.data;
  return <><PageHeading eyebrow="03 / RESOLVE THE OVERLAP" title="One study. One place in your review.">Confirm uncertain matches. Duplicate records are hidden, never deleted.</PageHeading><LoadState pending={duplicates.isPending} error={duplicates.error} retry={duplicates.refetch}/><Feedback action={action} success="Duplicate decision recorded."/>
    {data && <><div className="section-heading"><div><h2>Needs your review <span className="count-pill">{data.uncertain_pairs.length}</span></h2><p>Similarity suggests a match. You decide whether it is the same paper.</p></div></div><label htmlFor="duplicate-note">Decision note (optional)</label><input id="duplicate-note" value={note} onChange={event => setNote(event.target.value)} placeholder="Add context for your confirmations or rejections" className="duplicate-note"/>
      {!data.uncertain_pairs.length && <section className="panel"><Empty title="No uncertain pairs waiting">New candidates will appear here after deduplication.</Empty></section>}
      <div className="pair-list">{data.uncertain_pairs.map(pair => <article className="panel pair-card" key={pair.record_ids.join(':')}><div className="pair-top"><span className="status status-saved">Pending review</span><span className="similarity"><strong>{Math.round(pair.score * 100)}%</strong> similarity · {pair.match_type}</span></div><div className="pair-records">{pair.record_ids.map((id, index) => <div key={id}><span className="eyebrow">CANDIDATE {index + 1}</span><a href={`#/records/${id}`}>Record #{id} <Icon name="arrow" size={16}/></a><p>Open the record to compare its title, abstract and publication metadata.</p></div>)}</div><div className="pair-actions"><button className="btn btn-primary" disabled={action.isPending} onClick={() => action.mutate({ entity_type: 'pair', entity_id: [...pair.record_ids].sort((a, b) => a - b).join(':'), action: 'confirm', new_value: { status: 'confirmed' }, note })}><Icon name="check" size={16}/> Confirm duplicate</button><button className="btn" disabled={action.isPending} onClick={() => action.mutate({ entity_type: 'pair', entity_id: [...pair.record_ids].sort((a, b) => a - b).join(':'), action: 'reject', new_value: { status: 'rejected' }, note })}><Icon name="close" size={16}/> Keep separate</button></div></article>)}</div>
      <div className="section-heading"><div><h2>Duplicate groups <span className="count-pill">{data.groups.length}</span></h2><p>The representative remains visible. Every member remains stored.</p></div></div>
      {!data.groups.length && <section className="panel"><Empty title="No duplicate groups yet">Run the pipeline after pulling abstracts to identify matches.</Empty></section>}
      {data.groups.map(group => <article className="panel group-card" key={group.id}><div className="section-heading compact"><h3>Group #{group.id} <span className="muted">· {group.dedup_version}</span></h3><button className="btn btn-small" disabled={action.isPending} onClick={() => action.mutate({ entity_type: 'group', entity_id: group.id, action: 'split', new_value: { status: 'rejected' }, note })}>Split group</button></div>{group.members.map(member => <div className="member-row" key={member.record_id}><a href={`#/records/${member.record_id}`}>Record #{member.record_id}</a><span>{member.record_id === group.representative_record_id ? 'Representative' : ['rejected', 'pending'].includes(member.status) ? 'Visible' : 'Hidden duplicate'}</span><small>{member.match_type} · {Math.round(member.score * 100)}% · {member.status}</small></div>)}</article>)}
    </>}
  </>;
}

export function CriteriaPage() {
  const projectId = useProjectContext();
  const criteria = useQuery({ queryKey: ['criteria', projectId], queryFn: ({ signal }) => api.criteria(signal) });
  const action = useAction(({ key, active }: { key: string; active: boolean }) => api.toggleCriterion(key, active));
  return <><PageHeading eyebrow="04 / MAKE THE RULES EXPLICIT" title="A review with reasons you can see.">Choose your active screening criteria. Every toggle is recorded in the decision log.</PageHeading><div className="notice">After changing criteria, run the pipeline again from Queries. Human overrides remain intact.</div><LoadState pending={criteria.isPending} error={criteria.error} retry={criteria.refetch}/><Feedback action={action} success="Criterion updated and logged."/>
    {criteria.data?.length === 0 && <section className="panel"><Empty title="No criteria configured">Ask the backend maintainer to load the review’s criteria.</Empty></section>}
    <div className="criteria-grid">{criteria.data?.map(criterion => <article className="panel criterion-card" key={criterion.key}><div className="criterion-top"><span className="icon-tile"><Icon name="criteria"/></span><label className="switch-label"><input type="checkbox" role="switch" aria-label={`Enable ${criterion.label}`} checked={criterion.active} disabled={action.isPending} onChange={event => action.mutate({ key: criterion.key, active: event.target.checked })}/><span className="switch-track"/><span>{criterion.active ? 'Active' : 'Inactive'}</span></label></div><h2>{criterion.label}</h2><p>{criterion.description}</p><div className="criterion-reason"><strong>Why this matters</strong><p>{criterion.reason}</p></div><div className="criterion-footer"><code>{criterion.key}</code><span>{criterion.kind} · {criterion.source}</span></div></article>)}</div>
  </>;
}

export function ExportPage() {
  const projectId = useProjectContext();
  const queryId = useQueryContext();
  const included = useQuery({ queryKey: ['records', projectId, 'export-preview', queryId ?? null], queryFn: ({ signal }) => api.records({ query_id: queryId, label: 'include', limit: 1 }, signal) });
  const [downloaded, setDownloaded] = useState(false);
  const download = useAction(async () => {
    const blob = await api.exportCsv(queryId);
    const url = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'included-studies.csv'; document.body.append(anchor); anchor.click(); anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    setDownloaded(true);
  });
  return <><PageHeading eyebrow="05 / TAKE THE EVIDENCE WITH YOU" title="Ready for the next chapter.">Download the included studies in a format that travels with your review.</PageHeading><LoadState pending={included.isPending} error={included.error} retry={included.refetch}/><section className="panel export-card"><span className="export-icon"><Icon name="download" size={38}/></span><p className="eyebrow">INCLUDED STUDIES</p><h2>{included.data?.total ?? '—'} records, ready to export.</h2><p>Only visible studies with an effective Include label are exported.<br/>Reviewer overrides take precedence over machine labels.</p><div className="export-features"><span><Icon name="check" size={16}/> Excel-friendly UTF-8</span><span><Icon name="check" size={16}/> Abstracts & decision reasons</span><span><Icon name="check" size={16}/> Correct CSV quoting</span></div><button className="btn btn-primary" disabled={download.isPending || included.isPending || !!included.error} onClick={() => download.mutate()}><Icon name="download" size={18}/>{download.isPending ? 'Preparing download…' : 'Download included studies'}</button><Feedback action={download} success={downloaded ? 'CSV download started.' : undefined}/><p className="export-note">No records are changed or removed when you export.</p></section></>;
}

export function DecisionsPage() {
  const projectId = useProjectContext();
  const decisions = useQuery({ queryKey: ['decisions', projectId], queryFn: ({ signal }) => api.decisions(signal) });
  const action = useAction(api.decide);
  return <><PageHeading eyebrow="06 / KEEP THE REASONING" title="A history you can stand behind.">Every reviewer change, in order. Undo adds a new entry; the original stays intact.</PageHeading><LoadState pending={decisions.isPending} error={decisions.error} retry={decisions.refetch}/><Feedback action={action} success="Undo recorded as a new decision."/>
    {decisions.data && <section className="panel"><div className="table-caption"><strong>{decisions.data.length} logged decisions</strong><span>Append-only audit history</span></div>{!decisions.data.length ? <Empty title="Your decision log starts with your first review">Overrides, notes, criteria changes and annotation edits appear here.</Empty> : <div className="table-scroll"><table className="audit-table"><thead><tr><th>WHEN / WHO</th><th>ENTITY / ACTION</th><th>CHANGE / NOTE</th><th/></tr></thead><tbody>{[...decisions.data].reverse().map(decision => {
      const latest = [...decisions.data!].reverse().find(item => item.entity_type === decision.entity_type && String(item.entity_id) === String(decision.entity_id));
      return <tr key={decision.id}><td><strong>{dateText(decision.created_at)}</strong><small>{new Date(decision.created_at).toLocaleTimeString()} · {decision.actor}</small></td><td><strong>{decision.entity_type} #{decision.entity_id}</strong><small>{decision.action.replaceAll('_', ' ')}</small></td><td><details><summary>Inspect change</summary><div className="audit-values"><span>Before</span><code>{JSON.stringify(decision.old_value, null, 2)}</code><span>After</span><code>{JSON.stringify(decision.new_value, null, 2)}</code></div></details><p>{decision.note || 'No note provided.'}</p></td><td><button className="btn btn-small" disabled={action.isPending || latest?.id !== decision.id} onClick={() => action.mutate({ entity_type: decision.entity_type, entity_id: decision.entity_id, action: 'undo', new_value: null, note: `Undo decision #${decision.id}` })}>Undo latest</button></td></tr>;
    })}</tbody></table></div>}</section>}
  </>;
}
