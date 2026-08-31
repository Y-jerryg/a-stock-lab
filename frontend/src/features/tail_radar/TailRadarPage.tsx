import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Search, SlidersHorizontal } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { PageHeader } from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { ApiError } from '../../lib/api/client';
import type { StageStatus, TailRadarCandidateSummary } from './api';
import { EmptyPanel, ErrorPanel, Metric, StageBadge, WorkflowBadge } from './components';
import {
  formatCompactMoney,
  formatInteger,
  formatNumber,
  formatPercent,
  formatShanghaiTime,
} from './format';
import {
  latestTailRadarRunQuery,
  tailRadarCandidatesQuery,
  tailRadarRunSummaryQuery,
} from './queries';

type SortKey =
  'symbol' | 'pct_change' | 'price' | 'amount' | 'intraday_position' | 'previous_5m_return_pct';
type Density = 'compact' | 'comfortable';

export function TailRadarPage() {
  const latest = useQuery(latestTailRadarRunQuery);
  const runId = latest.data?.run_id ?? '';
  const summary = useQuery({ ...tailRadarRunSummaryQuery(runId), enabled: Boolean(runId) });
  const candidates = useQuery({ ...tailRadarCandidatesQuery(runId), enabled: Boolean(runId) });
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('pct_change');
  const [descending, setDescending] = useState(true);
  const [technicalFilter, setTechnicalFilter] = useState<StageStatus | 'all'>('all');
  const [researchFilter, setResearchFilter] = useState<StageStatus | 'all'>('all');
  const [density, setDensity] = useState<Density>('compact');
  const [page, setPage] = useState(1);
  const pageSize = density === 'compact' ? 25 : 15;

  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    const values = (candidates.data ?? []).filter((candidate) => {
      const matchesSearch =
        !needle ||
        candidate.symbol.includes(needle) ||
        (candidate.name?.toLocaleLowerCase().includes(needle) ?? false);
      return (
        matchesSearch &&
        (technicalFilter === 'all' || candidate.technical_status === technicalFilter) &&
        (researchFilter === 'all' || candidate.research_status === researchFilter)
      );
    });
    return values.sort((left, right) => compareCandidate(left, right, sortKey, descending));
  }, [candidates.data, descending, researchFilter, search, sortKey, technicalFilter]);

  useEffect(() => {
    setPage(1);
  }, [search, technicalFilter, researchFilter, density]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);

  if (latest.isLoading) return <OverviewSkeleton />;
  if (latest.error instanceof ApiError && latest.error.status === 404) {
    return (
      <div>
        <Header />
        <EmptyPanel
          title="No persisted Tail Radar run"
          description="The public interface is read-only. Run the internal workflow CLI before expecting market results here."
        />
      </div>
    );
  }
  if (latest.isError) return <PageError error={latest.error} />;
  if (summary.isLoading || candidates.isLoading) return <OverviewSkeleton />;
  if (summary.isError) return <PageError error={summary.error} />;
  if (candidates.isError) return <PageError error={candidates.error} />;
  if (!summary.data) return <PageError error={new Error('Run summary was empty.')} />;

  const run = summary.data.run;
  const snapshot = summary.data.snapshot;
  const workflow = summary.data.workflow;

  return (
    <div>
      <Header />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <Metric label="Trade date" value={run.trade_date} hint="Asia/Shanghai" />
        <Metric
          label="Intended snapshot"
          value={formatShanghaiTime(run.intended_snapshot_time).split(' ').at(-1)}
          hint={formatShanghaiTime(run.intended_snapshot_time)}
        />
        <Metric
          label="Actual fetch"
          value={formatShanghaiTime(snapshot.actual_fetch_finished_at).split(' ').at(-1)}
          hint={formatShanghaiTime(snapshot.actual_fetch_finished_at)}
        />
        <Metric
          label="Provider"
          value={snapshot.provider}
          hint={snapshot.provider_version ?? 'Version unavailable'}
        />
        <Metric
          label="Latency"
          value={`${formatNumber(snapshot.latency_ms, 0)} ms`}
          hint="Full-market request"
        />
        <Metric
          label="Scanned"
          value={formatInteger(snapshot.row_count)}
          hint="Normalized securities"
        />
        <Metric
          label="Candidates"
          value={formatInteger(run.candidate_count)}
          hint="Inclusive +2.00% to +3.00%"
        />
        <Metric
          label="Workflow"
          value={<WorkflowBadge status={workflow?.lifecycle} />}
          hint={snapshot.quality_report.passed ? 'Quality gate passed' : 'Quality gate failed'}
        />
      </div>

      <Card className="mt-5 overflow-hidden">
        <CardHeader className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h2 className="text-sm font-semibold">Point-in-time candidates</h2>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              {String(filtered.length)} visible of {String(candidates.data?.length ?? 0)} persisted
              candidates
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative min-w-56 flex-1 xl:flex-none">
              <span className="sr-only">Search candidates</span>
              <Search className="pointer-events-none absolute top-2.5 left-3 size-3.5 text-[var(--text-subtle)]" />
              <input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
                placeholder="Symbol or company"
                className="h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--surface)] pr-3 pl-9 text-sm outline-none focus:ring-2 focus:ring-[var(--focus)]"
              />
            </label>
            <SelectControl
              label="Technical status"
              value={technicalFilter}
              onChange={setTechnicalFilter}
            />
            <SelectControl
              label="AI status"
              value={researchFilter}
              onChange={setResearchFilter}
              includeNoEvidence
            />
            <label className="sr-only" htmlFor="candidate-sort">
              Sort candidates
            </label>
            <select
              id="candidate-sort"
              value={sortKey}
              onChange={(event) => {
                setSortKey(event.target.value as SortKey);
              }}
              className="h-9 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 text-xs"
            >
              <option value="pct_change">% change</option>
              <option value="symbol">Symbol</option>
              <option value="price">Price</option>
              <option value="amount">Turnover amount</option>
              <option value="intraday_position">Intraday position</option>
              <option value="previous_5m_return_pct">5m return</option>
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDescending((value) => !value);
              }}
              aria-label={`Sort ${descending ? 'ascending' : 'descending'}`}
            >
              {descending ? '↓ Desc' : '↑ Asc'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDensity((value) => (value === 'compact' ? 'comfortable' : 'compact'));
              }}
            >
              <SlidersHorizontal className="size-3.5" /> {density}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {visible.length === 0 ? (
            <div className="p-5">
              <EmptyPanel
                title="No candidates match these controls"
                description="Clear the search or status filters. Missing values are never synthesized."
              />
            </div>
          ) : (
            <CandidateTable candidates={visible} density={density} />
          )}
          <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3 text-xs text-[var(--text-muted)]">
            <span>
              Page {String(page)} of {String(pageCount)}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon"
                disabled={page <= 1}
                onClick={() => {
                  setPage((value) => value - 1);
                }}
                aria-label="Previous page"
              >
                <ChevronLeft className="size-4" />
              </Button>
              <Button
                variant="outline"
                size="icon"
                disabled={page >= pageCount}
                onClick={() => {
                  setPage((value) => value + 1);
                }}
                aria-label="Next page"
              >
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Header() {
  return (
    <PageHeader
      eyebrow="Research / Tail Radar"
      title="Tail Radar"
      description="Official point-in-time market evidence, deterministic analysis, and separately identified AI research."
    />
  );
}

function CandidateTable({
  candidates,
  density,
}: {
  candidates: TailRadarCandidateSummary[];
  density: Density;
}) {
  const cellPadding = density === 'compact' ? 'py-2.5' : 'py-4';
  const headers = [
    'Security',
    '% change',
    'Price',
    'Amount',
    'Turnover',
    'Position',
    'From high',
    '5m',
    '15m',
    '30m',
    'Technical',
    'AI research',
  ];
  return (
    <div className="max-h-[660px] overflow-auto">
      <table className="w-full min-w-[1320px] border-collapse text-left text-xs">
        <thead className="sticky top-0 z-10 bg-[var(--surface-muted)] text-[10px] tracking-wide text-[var(--text-subtle)] uppercase">
          <tr>
            {headers.map((label) => (
              <th key={label} className="border-b border-[var(--border)] px-4 py-3 font-semibold">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr
              key={candidate.candidate_id}
              className="border-b border-[var(--border)] transition-colors last:border-0 hover:bg-[var(--surface-hover)]"
            >
              <td className={`px-4 ${cellPadding}`}>
                <Link
                  to={`/tail-radar/candidates/${candidate.candidate_id}`}
                  className="font-semibold hover:text-[var(--accent)] hover:underline"
                >
                  {candidate.symbol}
                </Link>
                <div className="mt-0.5 max-w-40 truncate text-[11px] text-[var(--text-muted)]">
                  {candidate.name ?? 'Name unavailable'}
                </div>
              </td>
              <NumericCell value={formatPercent(candidate.pct_change)} positive />
              <NumericCell value={formatNumber(candidate.price)} />
              <NumericCell value={formatCompactMoney(candidate.amount)} />
              <NumericCell
                value={
                  candidate.turnover_rate == null
                    ? '—'
                    : `${formatNumber(candidate.turnover_rate)}%`
                }
              />
              <NumericCell
                value={
                  candidate.intraday_position == null
                    ? '—'
                    : formatNumber(candidate.intraday_position)
                }
              />
              <NumericCell value={formatPercent(candidate.distance_from_high_pct)} />
              <NumericCell value={formatPercent(candidate.previous_5m_return_pct)} />
              <NumericCell value={formatPercent(candidate.previous_15m_return_pct)} />
              <NumericCell value={formatPercent(candidate.previous_30m_return_pct)} />
              <td className={`px-4 ${cellPadding}`}>
                <StageBadge status={candidate.technical_status} />
              </td>
              <td className={`px-4 ${cellPadding}`}>
                <StageBadge status={candidate.research_status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function NumericCell({ value, positive = false }: { value: string; positive?: boolean }) {
  return (
    <td className={`px-4 font-mono tabular-nums ${positive ? 'font-semibold text-rose-500' : ''}`}>
      {value}
    </td>
  );
}

function SelectControl({
  label,
  value,
  onChange,
  includeNoEvidence = false,
}: {
  label: string;
  value: StageStatus | 'all';
  onChange: (value: StageStatus | 'all') => void;
  includeNoEvidence?: boolean;
}) {
  return (
    <label>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => {
          onChange(event.target.value as StageStatus | 'all');
        }}
        className="h-9 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 text-xs"
      >
        <option value="all">{label}: all</option>
        <option value="pending">Pending</option>
        <option value="running">Running</option>
        <option value="succeeded">Succeeded</option>
        {includeNoEvidence ? <option value="no_evidence">No evidence</option> : null}
        <option value="failed">Failed</option>
      </select>
    </label>
  );
}

function compareCandidate(
  left: TailRadarCandidateSummary,
  right: TailRadarCandidateSummary,
  key: SortKey,
  descending: boolean,
) {
  const leftValue = left[key];
  const rightValue = right[key];
  const direction = descending ? -1 : 1;
  if (leftValue == null && rightValue == null) return left.symbol.localeCompare(right.symbol);
  if (leftValue == null) return 1;
  if (rightValue == null) return -1;
  const comparison =
    typeof leftValue === 'string'
      ? leftValue.localeCompare(String(rightValue))
      : leftValue - Number(rightValue);
  return comparison * direction;
}

function OverviewSkeleton() {
  return (
    <div role="status" aria-label="Loading Tail Radar overview">
      <Header />
      <div className="grid animate-pulse gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        {Array.from({ length: 8 }, (_, index) => (
          <div key={index} className="h-28 rounded-lg bg-[var(--surface-muted)]" />
        ))}
      </div>
      <div className="mt-5 h-[520px] animate-pulse rounded-lg bg-[var(--surface-muted)]" />
    </div>
  );
}

function PageError({ error }: { error: unknown }) {
  return (
    <div>
      <Header />
      <ErrorPanel message={error instanceof Error ? error.message : 'Unexpected API error.'} />
    </div>
  );
}
