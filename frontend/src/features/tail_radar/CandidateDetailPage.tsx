import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ExternalLink, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react';
import { lazy, Suspense, useState, type ReactNode, type SyntheticEvent } from 'react';
import { Link, useParams } from 'react-router-dom';

import { PageHeader } from '../../components/PageHeader';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { ApiError } from '../../lib/api/client';
import { researchCandidate, type ResearchClaim, type StageStatus } from './api';
import { EmptyPanel, ErrorPanel, LoadingPanel, SectionLabel, StageBadge } from './components';
import {
  formatClaimClassification,
  formatBoard,
  formatCompactMoney,
  formatDataQuality,
  formatInteger,
  formatIntradayPosition,
  formatNumber,
  formatPathLabel,
  formatPercent,
  formatPublicationStatus,
  formatShanghaiTime,
  formatSourceAvailability,
} from './format';
import { tailRadarCandidateQuery, tailRadarResearchAvailabilityQuery } from './queries';

const IntradayChart = lazy(async () => {
  const module = await import('./IntradayChart');
  return { default: module.IntradayChart };
});

export function CandidateDetailPage() {
  const { candidateId = '' } = useParams();
  const query = useQuery({
    ...tailRadarCandidateQuery(candidateId),
    enabled: Boolean(candidateId),
  });

  if (query.isLoading) return <LoadingPanel label="正在加载候选标的研究证据" />;
  if (query.isError) {
    return (
      <ErrorPanel
        message={query.error instanceof Error ? query.error.message : '发生了未预期的接口错误。'}
      />
    );
  }
  if (!query.data)
    return <EmptyPanel title="候选标的不可用" description="接口没有返回已保存的候选标的数据。" />;
  const candidate = query.data;
  const snapshot = candidate.snapshot_data;
  const intraday = candidate.intraday_analysis;
  const research = candidate.web_research;

  return (
    <div>
      <Link
        to="/tail-radar"
        className="mb-4 inline-flex items-center gap-2 text-xs font-medium text-[var(--text-muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="size-3.5" /> 返回尾盘雷达
      </Link>
      <PageHeader
        eyebrow={`尾盘雷达 / ${candidate.trade_date}`}
        title={`${candidate.symbol}${snapshot.name ? ` · ${snapshot.name}` : ''}`}
        description="展示一条不可变快照筛选结果、对应的时点确定性计算，以及被单独标识的 AI 解释。"
      />

      <div className="mb-5 flex flex-wrap gap-2">
        <Badge variant="ready">符合筛选规则</Badge>
        <Badge variant="neutral">{formatBoard(candidate.board)}</Badge>
        <StageBadge status={candidate.workflow_state?.technical_status ?? null} />
        <StageBadge status={candidate.workflow_state?.research_status ?? null} />
        <Badge variant="neutral">资料截止时点 {formatShanghaiTime(candidate.as_of)}</Badge>
      </div>

      <section aria-labelledby="snapshot-evidence-title">
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <SectionLabel tone="raw">原始市场数据</SectionLabel>
              <h2 id="snapshot-evidence-title" className="mt-2 text-base font-semibold">
                快照证据
              </h2>
            </div>
            <p className="font-mono text-sm font-semibold text-rose-500">
              {formatPercent(snapshot.pct_change)}
            </p>
          </CardHeader>
          <CardContent>
            <FeatureGrid>
              <Field label="当前价格" value={formatNumber(snapshot.price)} />
              <Field label="涨跌额" value={formatNumber(snapshot.absolute_change)} />
              <Field label="昨收价" value={formatNumber(snapshot.previous_close)} />
              <Field label="开盘价" value={formatNumber(snapshot.open)} />
              <Field label="最高价" value={formatNumber(snapshot.high)} />
              <Field label="最低价" value={formatNumber(snapshot.low)} />
              <Field label="成交量" value={formatInteger(snapshot.volume)} />
              <Field label="成交额" value={formatCompactMoney(snapshot.amount)} />
              <Field
                label="换手率"
                value={
                  snapshot.turnover_rate == null ? '—' : `${formatNumber(snapshot.turnover_rate)}%`
                }
              />
              <Field
                label="振幅"
                value={snapshot.amplitude == null ? '—' : `${formatNumber(snapshot.amplitude)}%`}
              />
              <Field label="量比" value={formatNumber(snapshot.volume_ratio)} />
              <Field label="流通市值" value={formatCompactMoney(snapshot.float_market_cap)} />
            </FeatureGrid>
            <div className="mt-5 grid gap-3 border-t border-[var(--border)] pt-5 text-xs md:grid-cols-2 xl:grid-cols-4">
              <Field label="数据供应商" value={candidate.snapshot_evidence.provider} />
              <Field
                label="计划快照时点"
                value={formatShanghaiTime(candidate.snapshot_evidence.intended_snapshot_time)}
              />
              <Field
                label="实际采集完成时点"
                value={formatShanghaiTime(candidate.snapshot_evidence.actual_fetch_finished_at)}
              />
              <Field label="筛选规则版本" value={candidate.screening_rule_version} mono />
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="mt-5" aria-labelledby="deterministic-title">
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <SectionLabel tone="deterministic">确定性计算</SectionLabel>
              <h2 id="deterministic-title" className="mt-2 text-base font-semibold">
                日内特征分析
              </h2>
            </div>
            {intraday && (
              <Badge variant={intraday.data_quality.status === 'good' ? 'ready' : 'warning'}>
                数据质量：{formatDataQuality(intraday.data_quality.status)}
              </Badge>
            )}
          </CardHeader>
          <CardContent>
            {!intraday ? (
              <EmptyPanel
                title="尚无技术分析成果"
                description="该候选标的尚未保存时点日内特征分析结果。"
              />
            ) : (
              <div className="space-y-6">
                {intraday.used_bars && intraday.used_bars.length > 0 ? (
                  <Suspense
                    fallback={
                      <div className="h-80 animate-pulse rounded-md bg-[var(--surface-subtle)]" />
                    }
                  >
                    <IntradayChart bars={intraday.used_bars} symbol={candidate.symbol} />
                  </Suspense>
                ) : (
                  <div className="grid h-72 place-items-center rounded-md bg-[var(--surface-muted)] text-sm text-[var(--text-muted)]">
                    本次分析没有保存可用的时点分时数据序列。
                  </div>
                )}
                <div className="grid gap-5 xl:grid-cols-2">
                  <FeatureSection title="价格表现">
                    <Field
                      label="近5分钟收益率"
                      value={formatPercent(intraday.price.previous_5m_return_pct)}
                    />
                    <Field
                      label="近15分钟收益率"
                      value={formatPercent(intraday.price.previous_15m_return_pct)}
                    />
                    <Field
                      label="近30分钟收益率"
                      value={formatPercent(intraday.price.previous_30m_return_pct)}
                    />
                    <Field
                      label="开盘以来收益率"
                      value={formatPercent(intraday.price.return_since_open_pct)}
                    />
                    <Field
                      label="距日内最高点"
                      value={formatPercent(intraday.price.distance_from_intraday_high_pct)}
                    />
                    <Field
                      label="距日内最低点"
                      value={formatPercent(intraday.price.distance_from_intraday_low_pct)}
                    />
                    <Field
                      label="标准化日内位置"
                      value={formatIntradayPosition(intraday.price.normalized_intraday_position)}
                    />
                    <Field
                      label="相对日内高点回撤"
                      value={formatPercent(intraday.price.drawdown_from_intraday_high_pct)}
                    />
                  </FeatureSection>
                  <FeatureSection title="成交量与成交额表现">
                    <Field
                      label="近5分钟成交量"
                      value={formatInteger(intraday.volume.recent_5m_volume)}
                    />
                    <Field
                      label="上一可比5分钟成交量"
                      value={formatInteger(intraday.volume.previous_comparable_5m_volume)}
                    />
                    <Field
                      label="成交量加速比"
                      value={formatNumber(intraday.volume.recent_volume_acceleration_ratio)}
                    />
                    <Field
                      label="近期成交额"
                      value={formatCompactMoney(intraday.volume.recent_turnover_amount)}
                    />
                    <Field label="成交量加权均价" value={formatNumber(intraday.volume.vwap, 3)} />
                    <Field
                      label="距成交量加权均价"
                      value={formatPercent(intraday.volume.distance_from_vwap_pct)}
                    />
                  </FeatureSection>
                </div>
                <FeatureSection title="确定性走势描述">
                  {Object.entries(intraday.path).map(([key, value]) => (
                    <Field
                      key={key}
                      label={formatPathLabel(key)}
                      value={value == null ? '无法评估' : value ? '已检测到' : '未检测到'}
                    />
                  ))}
                </FeatureSection>
                <div className="grid gap-3 text-xs md:grid-cols-2 xl:grid-cols-4">
                  <Field label="分析截止时点" value={formatShanghaiTime(intraday.analysis_as_of)} />
                  <Field label="计算版本" value={intraday.calculation_version} mono />
                  <Field
                    label="特征结构版本"
                    value={`v${String(intraday.feature_schema_version)}`}
                    mono
                  />
                  <Field
                    label="使用分时条数 / 排除未来条数"
                    value={`${String(intraday.data_quality.used_bar_count)} / ${String(intraday.data_quality.future_bar_count)}`}
                  />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      <section className="mt-5" aria-labelledby="ai-research-title">
        <Card className="border-violet-500/20">
          <CardHeader className="flex flex-wrap items-center justify-between gap-3 bg-violet-500/[0.025]">
            <div>
              <SectionLabel tone="ai">AI 解释</SectionLabel>
              <h2 id="ai-research-title" className="mt-2 text-base font-semibold">
                基于证据的网络研究
              </h2>
            </div>
            {research && (
              <div className="text-right">
                <Badge variant={research.evidence_quality === 'insufficient' ? 'warning' : 'ready'}>
                  证据质量：{formatDataQuality(research.evidence_quality)}
                </Badge>
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  置信度 {formatNumber(research.confidence * 100, 0)}%
                </p>
              </div>
            )}
          </CardHeader>
          <CardContent>
            {!research ? (
              <OnDemandResearchPanel
                candidateId={candidate.candidate_id}
                researchStatus={candidate.workflow_state?.research_status ?? null}
              />
            ) : (
              <div className="space-y-6">
                <div className="rounded-md border border-violet-500/20 bg-violet-500/5 p-4">
                  <div className="flex items-start gap-3">
                    <ShieldCheck className="mt-0.5 size-4 shrink-0 text-violet-500" />
                    <p className="text-sm leading-6">{research.concise_summary}</p>
                  </div>
                </div>
                <div className="grid gap-5 xl:grid-cols-2">
                  <ClaimSection
                    title="已核实事实"
                    claims={research.verified_facts}
                    empty="在资料截止时点前没有可核实的事实。"
                  />
                  <ClaimSection
                    title="可能驱动因素"
                    claims={research.likely_drivers}
                    empty="未识别出有证据支持的驱动因素。"
                  />
                  <ClaimSection title="公司背景" claims={research.company_context} />
                  <ClaimSection title="行业背景" claims={research.sector_context} />
                  <ClaimSection title="市场背景" claims={research.market_context} />
                  <ClaimSection title="积极因素" claims={research.positive_factors} />
                  <ClaimSection title="风险因素" claims={research.risk_factors} />
                  <TextList title="尚待解决的问题" values={research.unresolved_questions} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold">研究来源</h3>
                  {research.sources.length === 0 ? (
                    <p className="mt-2 text-sm text-[var(--text-muted)]">
                      没有保存可用的网络来源。
                    </p>
                  ) : (
                    <div className="mt-3 divide-y divide-[var(--border)] rounded-md border border-[var(--border)]">
                      {research.sources.map((source) => (
                        <a
                          key={source.source_id}
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-start justify-between gap-4 p-4 transition-colors hover:bg-[var(--surface-hover)]"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">
                              {source.title ?? source.publisher_domain}
                            </p>
                            <p className="mt-1 text-xs text-[var(--text-muted)]">
                              {source.publisher_domain} · 发布时间{' '}
                              {formatShanghaiTime(source.published_at)} ·{' '}
                              {formatPublicationStatus(source.publication_timestamp_status)}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[var(--text-subtle)]">
                              <Badge
                                variant={
                                  source.availability_at_as_of === 'available_at_as_of'
                                    ? 'ready'
                                    : 'warning'
                                }
                              >
                                {formatSourceAvailability(source.availability_at_as_of)}
                              </Badge>
                              <span>检索时间 {formatShanghaiTime(source.retrieved_at)}</span>
                              <span>
                                关联 {String(source.relationship_claim_ids.length)} 条论述
                              </span>
                            </div>
                          </div>
                          <ExternalLink className="mt-0.5 size-4 shrink-0 text-[var(--text-subtle)]" />
                        </a>
                      ))}
                    </div>
                  )}
                </div>
                <div className="grid gap-3 border-t border-[var(--border)] pt-5 text-xs md:grid-cols-2 xl:grid-cols-4">
                  <Field label="研究截止时点" value={formatShanghaiTime(research.analysis_as_of)} />
                  <Field label="提示词版本" value={research.prompt_version} mono />
                  <Field label="模型" value={research.model_identifier} mono />
                  <Field label="创建时间" value={formatShanghaiTime(research.created_at)} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function OnDemandResearchPanel({
  candidateId,
  researchStatus,
}: {
  candidateId: string;
  researchStatus: StageStatus | null;
}) {
  const queryClient = useQueryClient();
  const availability = useQuery(tailRadarResearchAvailabilityQuery);
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const retryFailed = researchStatus === 'failed';
  const mutation = useMutation({
    mutationFn: () => researchCandidate(candidateId, openaiApiKey.trim(), retryFailed),
    onSuccess: () => {
      setOpenaiApiKey('');
      setConfirmed(false);
    },
    onError: () => {
      setOpenaiApiKey('');
      setConfirmed(false);
    },
    onSettled: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['tail-radar', 'candidates', candidateId],
      });
    },
  });

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed || !openaiApiKey.trim() || mutation.isPending) return;
    mutation.mutate();
  }

  if (availability.isLoading) {
    return <LoadingPanel label="正在检查按需 AI 研究配置" />;
  }
  if (availability.isError || !availability.data?.enabled) {
    return (
      <div className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-5">
        <h3 className="font-semibold">AI 研究尚未启用</h3>
        <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
          浏览详情和确定性数据不会调用 OpenAI。站点管理员只需在后端开启按需研究；分析时由每位用户
          临时输入自己的 OpenAI API Key。
        </p>
      </div>
    );
  }

  const alreadyRunning = researchStatus === 'running';
  return (
    <form
      onSubmit={submit}
      className="rounded-md border border-violet-500/20 bg-violet-500/[0.035] p-5"
    >
      <div className="flex items-start gap-3">
        <Sparkles className="mt-0.5 size-5 shrink-0 text-violet-500" />
        <div>
          <h3 className="font-semibold">{retryFailed ? '重新研究这只股票' : '按需研究这只股票'}</h3>
          <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
            只有提交此表单才会调用 OpenAI；本次只分析当前股票，不会批量分析其他候选。模型为{' '}
            <span className="font-mono">{availability.data.model_identifier}</span>。
          </p>
        </div>
      </div>
      <div className="mt-5 max-w-xl space-y-4">
        <label className="block">
          <span className="text-xs font-semibold">你的 OpenAI 接口密钥</span>
          <span className="relative mt-2 block">
            <LockKeyhole className="pointer-events-none absolute top-2.5 left-3 size-4 text-[var(--text-subtle)]" />
            <input
              type="password"
              value={openaiApiKey}
              onChange={(event) => {
                setOpenaiApiKey(event.target.value);
              }}
              autoComplete="off"
              spellCheck={false}
              placeholder="输入你自己的 OpenAI 接口密钥"
              className="h-10 w-full rounded-md border border-[var(--border-strong)] bg-[var(--surface)] pr-3 pl-10 text-sm outline-none focus:ring-2 focus:ring-[var(--focus)]"
              disabled={mutation.isPending || alreadyRunning}
            />
          </span>
          <span className="mt-1 block text-[11px] text-[var(--text-subtle)]">
            密钥只保存在当前页面内存，并仅发送给 A-Stock Lab 后端完成这一次请求；系统不会把密钥
            写入数据库、网址、浏览器存储、日志或前端构建产物。公开部署时必须使用 HTTPS，并且你必须
            信任该站点的后端运营者。建议使用单独、权限受限且设置了消费上限的项目密钥，使用后及时
            轮换或删除。
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm leading-5">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => {
              setConfirmed(event.target.checked);
            }}
            className="mt-1"
            disabled={mutation.isPending || alreadyRunning}
          />
          <span>
            我确认仅分析当前股票，并理解这一次操作可能产生 OpenAI 模型与网络搜索费用。
            {retryFailed ? '这是对失败任务的再次付费尝试。' : ''}
          </span>
        </label>
        {mutation.error ? (
          <p className="text-sm text-rose-600" role="alert">
            {mutation.error instanceof ApiError
              ? mutation.error.message
              : 'AI 研究请求失败，请稍后再试。'}
          </p>
        ) : null}
        <Button
          type="submit"
          disabled={!confirmed || !openaiApiKey.trim() || mutation.isPending || alreadyRunning}
        >
          {mutation.isPending
            ? '正在分析当前股票…'
            : alreadyRunning
              ? '当前股票正在分析'
              : retryFailed
                ? '确认重试当前股票'
                : '确认并分析当前股票'}
        </Button>
      </div>
    </form>
  );
}

function FeatureGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
      {children}
    </div>
  );
}

function FeatureSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)]/35 p-4">
      <h3 className="text-xs font-semibold tracking-wide text-[var(--text-muted)] uppercase">
        {title}
      </h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">{children}</div>
    </div>
  );
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-semibold tracking-wide text-[var(--text-subtle)] uppercase">
        {label}
      </p>
      <p
        className={`mt-1 truncate text-sm ${mono ? 'font-mono text-xs' : 'font-medium tabular-nums'}`}
      >
        {value}
      </p>
    </div>
  );
}

function ClaimSection({
  title,
  claims,
  empty = '没有保存相关论述。',
}: {
  title: string;
  claims: ResearchClaim[];
  empty?: string;
}) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {claims.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--text-muted)]">{empty}</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {claims.map((claim) => (
            <li
              key={claim.claim_id}
              className="rounded-md border border-[var(--border)] p-3 text-sm leading-6"
            >
              <Badge
                variant={
                  claim.classification === 'verified_fact'
                    ? 'ready'
                    : claim.classification === 'interpretation'
                      ? 'neutral'
                      : 'warning'
                }
              >
                {formatClaimClassification(claim.classification)}
              </Badge>
              <p className="mt-2">{claim.statement}</p>
              <p className="mt-1 text-[10px] text-[var(--text-subtle)]">
                关联 {String(claim.source_ids.length)} 个来源
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TextList({ title, values }: { title: string; values: string[] }) {
  return (
    <div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {values.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--text-muted)]">没有保存相关内容。</p>
      ) : (
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6">
          {values.map((value) => (
            <li key={value}>{value}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
