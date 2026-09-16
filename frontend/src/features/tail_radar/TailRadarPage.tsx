import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Search, SlidersHorizontal } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { PageHeader } from '../../components/PageHeader';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { ApiError } from '../../lib/api/client';
import type { AShareBoard, StageStatus, TailRadarCandidateSummary } from './api';
import { EmptyPanel, ErrorPanel, Metric, StageBadge, WorkflowBadge } from './components';
import {
  formatCompactMoney,
  formatBoard,
  formatInteger,
  formatIntradayPosition,
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
  const [boardFilter, setBoardFilter] = useState<AShareBoard | 'all'>('all');
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
        (boardFilter === 'all' || candidate.board === boardFilter) &&
        (technicalFilter === 'all' || candidate.technical_status === technicalFilter) &&
        (researchFilter === 'all' || candidate.research_status === researchFilter)
      );
    });
    return values.sort((left, right) => compareCandidate(left, right, sortKey, descending));
  }, [boardFilter, candidates.data, descending, researchFilter, search, sortKey, technicalFilter]);

  useEffect(() => {
    setPage(1);
  }, [search, boardFilter, technicalFilter, researchFilter, density]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);

  if (latest.isLoading) return <OverviewSkeleton />;
  if (latest.error instanceof ApiError && latest.error.status === 404) {
    return (
      <div>
        <Header />
        <EmptyPanel
          title="尚无尾盘雷达运行记录"
          description="公共网页仅提供只读查询。请先通过内部命令执行工作流，随后才能在这里看到真实市场结果。"
        />
      </div>
    );
  }
  if (latest.isError) return <PageError error={latest.error} />;
  if (summary.isLoading || candidates.isLoading) return <OverviewSkeleton />;
  if (summary.isError) return <PageError error={summary.error} />;
  if (candidates.isError) return <PageError error={candidates.error} />;
  if (!summary.data) return <PageError error={new Error('运行摘要为空。')} />;

  const run = summary.data.run;
  const snapshot = summary.data.snapshot;
  const workflow = summary.data.workflow;

  return (
    <div>
      <Header />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <Metric label="交易日期" value={run.trade_date} hint="亚洲/上海时区" />
        <Metric
          label="计划快照时点"
          value={formatShanghaiTime(run.intended_snapshot_time).split(' ').at(-1)}
          hint={formatShanghaiTime(run.intended_snapshot_time)}
        />
        <Metric
          label="实际采集完成"
          value={formatShanghaiTime(snapshot.actual_fetch_finished_at).split(' ').at(-1)}
          hint={formatShanghaiTime(snapshot.actual_fetch_finished_at)}
        />
        <Metric
          label="数据供应商"
          value={snapshot.provider}
          hint={snapshot.provider_version ?? '版本信息不可用'}
        />
        <Metric
          label="采集延迟"
          value={`${formatNumber(snapshot.latency_ms, 0)} 毫秒`}
          hint="全市场请求"
        />
        <Metric label="扫描数量" value={formatInteger(snapshot.row_count)} hint="已标准化证券" />
        <Metric
          label="候选数量"
          value={formatInteger(run.candidate_count)}
          hint={`${run.screening_rule_version === 'tail-radar-screen-v1' ? '历史规则：' : ''}涨幅含边界 +${run.rule_configuration.pct_change_min.toFixed(2)}% 至 +${run.rule_configuration.pct_change_max.toFixed(2)}%`}
        />
        <Metric
          label="工作流状态"
          value={<WorkflowBadge status={workflow?.lifecycle} />}
          hint={snapshot.quality_report.passed ? '数据质量校验通过' : '数据质量校验未通过'}
        />
      </div>

      <Card className="mt-5 overflow-hidden">
        <CardHeader className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <h2 className="text-sm font-semibold">时点候选标的</h2>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              已显示 {String(filtered.length)} 个，共保存 {String(candidates.data?.length ?? 0)}{' '}
              个候选标的
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative min-w-56 flex-1 xl:flex-none">
              <span className="sr-only">搜索候选标的</span>
              <Search className="pointer-events-none absolute top-2.5 left-3 size-3.5 text-[var(--text-subtle)]" />
              <input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                }}
                placeholder="股票代码或公司名称"
                className="h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--surface)] pr-3 pl-9 text-sm outline-none focus:ring-2 focus:ring-[var(--focus)]"
              />
            </label>
            <SelectControl
              label="上市板块"
              value={boardFilter}
              onChange={setBoardFilter}
              options={BOARD_OPTIONS}
            />
            <SelectControl
              label="技术分析状态"
              value={technicalFilter}
              onChange={setTechnicalFilter}
            />
            <SelectControl
              label="AI 研究状态"
              value={researchFilter}
              onChange={setResearchFilter}
              includeNoEvidence
            />
            <label className="sr-only" htmlFor="candidate-sort">
              候选标的排序
            </label>
            <select
              id="candidate-sort"
              value={sortKey}
              onChange={(event) => {
                setSortKey(event.target.value as SortKey);
              }}
              className="h-9 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 text-xs"
            >
              <option value="pct_change">涨跌幅</option>
              <option value="symbol">股票代码</option>
              <option value="price">价格</option>
              <option value="amount">成交额</option>
              <option value="intraday_position">日内位置</option>
              <option value="previous_5m_return_pct">近5分钟收益率</option>
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDescending((value) => !value);
              }}
              aria-label={`切换为${descending ? '升序' : '降序'}排列`}
            >
              {descending ? '↓ 降序' : '↑ 升序'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setDensity((value) => (value === 'compact' ? 'comfortable' : 'compact'));
              }}
            >
              <SlidersHorizontal className="size-3.5" />
              {density === 'compact' ? '紧凑' : '舒适'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {visible.length === 0 ? (
            <div className="p-5">
              <EmptyPanel
                title="没有符合当前条件的候选标的"
                description="请清除搜索内容或状态筛选。系统不会为缺失字段编造数值。"
              />
            </div>
          ) : (
            <CandidateTable candidates={visible} density={density} />
          )}
          <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3 text-xs text-[var(--text-muted)]">
            <span>
              第 {String(page)} 页，共 {String(pageCount)} 页
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="icon"
                disabled={page <= 1}
                onClick={() => {
                  setPage((value) => value - 1);
                }}
                aria-label="上一页"
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
                aria-label="下一页"
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
      eyebrow="研究 / 尾盘雷达"
      title="尾盘雷达"
      description="展示官方时点市场证据、确定性分析，以及与市场事实明确分离的 AI 研究。"
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
    '证券',
    '上市板块',
    '涨跌幅',
    '价格',
    '成交额',
    '换手率',
    '量比',
    '振幅',
    '流通市值',
    '日内位置',
    '距最高点',
    '近5分钟',
    '近15分钟',
    '近30分钟',
    '技术分析',
    'AI 研究',
  ];
  return (
    <div className="max-h-[660px] overflow-auto">
      <table className="w-full min-w-[1640px] border-collapse text-left text-xs">
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
                  {candidate.name ?? '名称不可用'}
                </div>
              </td>
              <td className={`px-4 ${cellPadding}`}>{formatBoard(candidate.board)}</td>
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
              <NumericCell value={formatNumber(candidate.volume_ratio)} />
              <NumericCell
                value={candidate.amplitude == null ? '—' : `${formatNumber(candidate.amplitude)}%`}
              />
              <NumericCell value={formatCompactMoney(candidate.float_market_cap)} />
              <NumericCell value={formatIntradayPosition(candidate.intraday_position)} />
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

function SelectControl<T extends string>({
  label,
  value,
  onChange,
  includeNoEvidence = false,
  options,
}: {
  label: string;
  value: T | 'all';
  onChange: (value: T | 'all') => void;
  includeNoEvidence?: boolean;
  options?: readonly { value: string; label: string }[];
}) {
  return (
    <label>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => {
          onChange(event.target.value as T | 'all');
        }}
        className="h-9 rounded-md border border-[var(--border-strong)] bg-[var(--surface)] px-3 text-xs"
      >
        <option value="all">{label}：全部</option>
        {options ? (
          options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))
        ) : (
          <>
            <option value="pending">待处理</option>
            <option value="running">进行中</option>
            <option value="succeeded">已完成</option>
            {includeNoEvidence ? <option value="no_evidence">无有效证据</option> : null}
            <option value="failed">失败</option>
          </>
        )}
      </select>
    </label>
  );
}

const BOARD_OPTIONS = [
  { value: 'shanghai_main', label: '沪市主板' },
  { value: 'shenzhen_main', label: '深市主板' },
  { value: 'chinext', label: '创业板' },
  { value: 'star', label: '科创板' },
  { value: 'beijing', label: '北交所' },
] as const;

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
    <div role="status" aria-label="正在加载尾盘雷达总览">
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
      <ErrorPanel message={error instanceof Error ? error.message : '发生了未预期的接口错误。'} />
    </div>
  );
}
