import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, isMockMode } from './api';
import { Icon, LoadState, useAction, useRoute, useQueryContext, useProjectContext, queryLink } from './components';
import { QueriesPage, RecordsPage, RecordPageView, DuplicatesPage, CriteriaPage, ExportPage, DecisionsPage } from './pages';

const links = [
  { path: '/queries', icon: 'search', label: 'Queries' },
  { path: '/records', icon: 'records', label: 'Records' },
  { path: '/duplicates', icon: 'duplicates', label: 'Duplicates' },
  { path: '/criteria', icon: 'criteria', label: 'Criteria' },
  { path: '/export', icon: 'download', label: 'Export' },
  { path: '/decisions', icon: 'history', label: 'Decision log' },
];

export default function App() {
  const route = useRoute().split('?')[0];
  const queryId = useQueryContext();
  const projectId = useProjectContext();
  const projects = useQuery({ queryKey: ['projects', projectId], queryFn: ({ signal }) => api.projects(signal) });
  const [creating, setCreating] = useState(false), [title, setTitle] = useState('');
  const createProject = useAction(api.createProject);
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ['runs', projectId], queryFn: ({ signal }) => api.runs(undefined, signal), refetchInterval: query => query.state.data?.some(run => ['queued', 'running'].includes(run.status)) ? 1200 : false });
  const finishedJobs = runs.data?.filter(run => ['completed', 'failed'].includes(run.status)).map(run => `${run.id}:${run.status}`).join(',');
  useEffect(() => {
    if (finishedJobs) for (const key of ['queries', 'records', 'record', 'duplicates']) void queryClient.invalidateQueries({ queryKey: [key] });
  }, [finishedJobs, queryClient]);
  const health = useQuery({ queryKey: ['health', projectId], queryFn: ({ signal }) => api.health(signal), refetchInterval: isMockMode() ? false : 30000 });
  const active = links.find(link => route === link.path || route.startsWith(link.path + '/'));
  const recordId = /^\/records\/(\d+)$/.exec(route)?.[1];
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>Skip to content</a>
    <aside className="sidebar">
      <a className="brand" href={queryLink('/queries', undefined, projectId)} aria-label="Mini-Rayyan home"><span className="brand-symbol"><Icon name="leaf" size={24}/></span><span>mini<span className="brand-light">rayyan</span><small>EVIDENCE, WITH CLARITY</small></span></a>
      <section className="search-threads" aria-label="Search threads">
        <div className="workspace-label">SEARCHES <span>{projects.data?.length ?? 0}</span></div>
        <button className="btn btn-small full-width" onClick={() => setCreating(true)}><Icon name="plus" size={15}/> New search</button>
        {creating && <form className="thread-form" onSubmit={event => {
          event.preventDefault(); if (!title.trim()) return;
          createProject.mutate(title.trim(), { onSuccess: project => {
            window.location.hash = queryLink('/queries', undefined, project.id);
            setCreating(false); setTitle('');
          } });
        }}><label htmlFor="thread-title">Search title</label><input id="thread-title" required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} autoFocus/>
          <button className="btn btn-small" disabled={createProject.isPending}>Create search</button><button className="text-button" type="button" onClick={() => setCreating(false)}>Cancel</button>
          {createProject.error && <p role="alert">{createProject.error.message}</p>}
        </form>}
        <LoadState pending={projects.isPending} error={projects.error} retry={projects.refetch}/>
        <div className="thread-list">{projects.data?.map(project => <a className={`thread-link ${project.id === projectId ? 'selected' : ''}`} key={project.id} href={queryLink('/queries', undefined, project.id)} aria-current={project.id === projectId ? 'page' : undefined}>{project.title}</a>)}</div>
      </section>
      <nav aria-label="Main navigation">{links.map(link => <a key={link.path} href={queryLink(link.path, queryId, projectId)} className={`nav-link ${active?.path === link.path ? 'active' : ''}`} aria-current={active?.path === link.path ? 'page' : undefined}><Icon name={link.icon}/><span>{link.label}</span>{active?.path === link.path && <span className="nav-dot"/>}</a>)}</nav>
      <div className="sidebar-bottom"><div className="reviewer-avatar">R</div><div><strong>Review workspace</strong><small>Every decision stays yours.</small></div></div>
    </aside>
    <div className="workspace-main">
      <header className="topbar"><div className="breadcrumb">Literature review <span>/</span> <strong>{recordId ? 'Record detail' : active?.label ?? 'Page not found'}</strong></div><span className={`connection ${health.error ? 'offline' : ''}`} title={health.error?.message}><span/>{isMockMode() ? 'Mock workspace' : health.isPending ? 'Connecting…' : health.error ? 'API unavailable' : 'API connected'}</span></header>
      <main id="main-content" tabIndex={-1}>
        <p className="notice">Search histories are separate. Review decisions, duplicate groups and criteria are still shared across searches.</p>
        {isMockMode() && <div className="demo-banner"><span className="demo-label">DEMO</span> Fictional example data. Changes stay in this browser tab.</div>}
        {route === '/queries' ? <QueriesPage key={projectId}/> : route === '/records' ? <RecordsPage key={projectId}/> : recordId ? <RecordPageView key={`${projectId}:${recordId}`} id={Number(recordId)}/> : route === '/duplicates' ? <DuplicatesPage/> : route === '/criteria' ? <CriteriaPage/> : route === '/export' ? <ExportPage/> : route === '/decisions' ? <DecisionsPage/> : <div className="empty"><h1>Page not found</h1><a className="btn" href={queryLink('/queries', undefined, projectId)}>Go to queries</a></div>}
      </main>
      <footer><span><Icon name="book" size={15}/> Powered by PubMed · Built for thoughtful review</span><p>NCBI/NLM provides PubMed content without endorsing individual studies. Abstracts may be copyrighted; do not redistribute them. <a href="https://www.ncbi.nlm.nih.gov/home/about/policies/" target="_blank" rel="noreferrer">NCBI disclaimer ↗</a></p></footer>
    </div>
  </div>;
}
