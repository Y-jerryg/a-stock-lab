import { AlertTriangle, Database, LoaderCircle } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge } from '../../components/ui/badge';
import { cn } from '../../lib/utils';
import type { StageStatus, WorkflowLifecycle } from './api';

export function SectionLabel({
  tone,
  children,
}: {
  tone: 'raw' | 'deterministic' | 'ai';
  children: ReactNode;
}) {
  const styles = {
    raw: 'border-sky-500/25 bg-sky-500/10 text-sky-600',
    deterministic: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-600',
    ai: 'border-violet-500/25 bg-violet-500/10 text-violet-600',
  };
  return (
    <span
      className={cn(
        'inline-flex rounded border px-2 py-1 text-[10px] font-bold tracking-[0.12em] uppercase',
        styles[tone],
      )}
    >
      {children}
    </span>
  );
}

export function StageBadge({ status }: { status: StageStatus | null }) {
  if (!status) return <Badge variant="neutral">Unavailable</Badge>;
  const variant =
    status === 'succeeded' || status === 'no_evidence'
      ? 'ready'
      : status === 'failed'
        ? 'warning'
        : 'neutral';
  return <Badge variant={variant}>{status.replaceAll('_', ' ')}</Badge>;
}

export function WorkflowBadge({ status }: { status: WorkflowLifecycle | undefined }) {
  if (!status) return <Badge variant="neutral">Legacy run</Badge>;
  return (
    <Badge
      variant={
        status === 'succeeded' ? 'ready' : status === 'partial_success' ? 'warning' : 'neutral'
      }
    >
      {status.replaceAll('_', ' ')}
    </Badge>
  );
}

export function LoadingPanel({ label = 'Loading Tail Radar data' }: { label?: string }) {
  return (
    <div
      className="grid min-h-72 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface)]"
      role="status"
    >
      <div className="text-center text-sm text-[var(--text-muted)]">
        <LoaderCircle className="mx-auto mb-3 size-5 animate-spin text-[var(--accent)]" />
        {label}
      </div>
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div
      className="grid min-h-72 place-items-center rounded-lg border border-rose-500/25 bg-rose-500/5 p-8 text-center"
      role="alert"
    >
      <div className="max-w-md">
        <AlertTriangle className="mx-auto mb-3 size-6 text-rose-500" />
        <h2 className="font-semibold">Tail Radar data could not be loaded</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{message}</p>
      </div>
    </div>
  );
}

export function EmptyPanel({ title, description }: { title: string; description: string }) {
  return (
    <div className="grid min-h-72 place-items-center rounded-lg border border-[var(--border)] bg-[var(--surface)] p-8 text-center">
      <div className="max-w-md">
        <Database className="mx-auto mb-3 size-6 text-[var(--text-subtle)]" />
        <h2 className="font-semibold">{title}</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{description}</p>
      </div>
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-card)]">
      <p className="text-[10px] font-semibold tracking-[0.12em] text-[var(--text-subtle)] uppercase">
        {label}
      </p>
      <div className="mt-2 truncate font-mono text-xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 truncate text-xs text-[var(--text-muted)]">{hint}</div>}
    </div>
  );
}
