import { Fragment, type ReactNode, useSyncExternalStore } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Label, PicoSpan } from './types';

const paths: Record<string, ReactNode> = {
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  records: <><path d="M7 3h10l4 4v14H3V3zM7 8h5M7 12h10M7 16h10"/></>,
  duplicates: <><rect x="3" y="3" width="12" height="14" rx="2"/><path d="M18 7h3v14H9v-2"/></>,
  criteria: <><path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></>,
  history: <><path d="M3 10a9 9 0 1 1 1 7M3 4v6h6M12 7v6l4 2"/></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  plus: <path d="M12 4v16M4 12h16"/>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  leaf: <><path d="M5 20C1 7 11 1 21 3c1 11-7 17-16 17ZM5 20 16 9"/></>,
  book: <><path d="M12 5C8 2 3 3 3 3v16s5-1 9 2c4-3 9-2 9-2V3s-5-1-9 2Zm0 0v16"/></>,
};
export function Icon({ name, size = 19 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? paths.records}</svg>;
}
const labels: Record<Label, string> = { include: 'Include', exclude: 'Exclude', maybe: 'Maybe' };
export function Badge({ label }: { label: Label }) { return <span className={`badge badge-${label}`}><span className="badge-dot"/>{labels[label]}</span>; }
export function PageHeading({ eyebrow, title, children, action }: { eyebrow: string; title: string; children: ReactNode; action?: ReactNode }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{children}</p></div>{action}</div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><span className="empty-icon"><Icon name="book" size={27}/></span><h3>{title}</h3><p>{children}</p></div>;
}
export function LoadState({ pending, error, retry }: { pending?: boolean; error?: Error | null; retry?: () => unknown }) {
  if (error) return <div className="notice notice-error" role="alert"><span>{error.message}</span>{retry && <button className="btn btn-small" onClick={() => retry()}>Try again</button>}</div>;
  return pending ? <p className="loading" role="status"><span className="spinner"/> Loading your workspace…</p> : null;
}
export function Feedback({ action, success }: { action: { isPending: boolean; isSuccess: boolean; error: Error | null }; success?: string }) {
  return <div aria-live="polite">{action.error && <p className="notice notice-error" role="alert">{action.error.message}</p>}{action.isSuccess && success && <p className="notice notice-success">{success}</p>}</div>;
}
export function useAction<T, R>(mutationFn: (value: T) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({ mutationFn, onSuccess: async () => {
    // An initial GET may still contain the pre-mutation snapshot. Cancel it
    // before refetching, including cached pages that are currently inactive.
    await client.cancelQueries();
    await client.invalidateQueries({ refetchType: 'all' });
  } });
}
export const picoLabels = { P: 'Population', I: 'Intervention', C: 'Comparator', O: 'Outcome' };

/** Python offsets count Unicode code points. React escapes every rendered string.
 * Segmenting at all boundaries preserves overlapping tags without using HTML injection.
 */
export function PicoAbstract({ text, spans }: { text: string; spans: PicoSpan[] }) {
  const chars = Array.from(text);
  const valid = spans.filter(span => Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end > span.start && span.end <= chars.length && chars.slice(span.start, span.end).join('') === span.text);
  const cuts = [...new Set([0, chars.length, ...valid.flatMap(span => [span.start, span.end])])].sort((a, b) => a - b);
  return <div className="abstract-text">{cuts.slice(0, -1).map((start, index) => {
    const end = cuts[index + 1], segment = chars.slice(start, end).join('');
    const active = valid.filter(span => span.start <= start && span.end >= end);
    return active.length ? <mark key={start} className={`pico-${active[0].label}`} title={active.map(span => picoLabels[span.label]).join(' + ')}>{segment}</mark> : <Fragment key={start}>{segment}</Fragment>;
  })}</div>;
}
export function dateText(value: string) { return new Date(value).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
const subscribe = (callback: () => void) => { window.addEventListener('hashchange', callback); return () => window.removeEventListener('hashchange', callback); };
export function useRoute() { return useSyncExternalStore(subscribe, () => window.location.hash.slice(1) || '/queries'); }
