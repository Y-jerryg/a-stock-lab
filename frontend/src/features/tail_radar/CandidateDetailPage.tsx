import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ExternalLink, ShieldCheck } from 'lucide-react';
import { lazy, Suspense, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';

import { PageHeader } from '../../components/PageHeader';
import { Badge } from '../../components/ui/badge';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import type { ResearchClaim } from './api';
import { EmptyPanel, ErrorPanel, LoadingPanel, SectionLabel, StageBadge } from './components';
import {
  formatCompactMoney,
  formatInteger,
  formatNumber,
  formatPercent,
  formatShanghaiTime,
} from './format';
import { tailRadarCandidateQuery } from './queries';

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

  if (query.isLoading) return <LoadingPanel label="Loading candidate research evidence" />;
  if (query.isError) {
    return (
      <ErrorPanel
        message={query.error instanceof Error ? query.error.message : 'Unexpected API error.'}
      />
    );
  }
  if (!query.data)
    return (
      <EmptyPanel
        title="Candidate unavailable"
        description="No persisted candidate payload was returned."
      />
    );
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
        <ArrowLeft className="size-3.5" /> Back to Tail Radar
      </Link>
      <PageHeader
        eyebrow={`Tail Radar / ${candidate.trade_date}`}
        title={`${candidate.symbol}${snapshot.name ? ` · ${snapshot.name}` : ''}`}
        description="One immutable snapshot decision, its deterministic point-in-time calculations, and separately labeled AI interpretation."
      />

      <div className="mb-5 flex flex-wrap gap-2">
        <Badge variant="ready">Rule included</Badge>
        <StageBadge status={candidate.workflow_state?.technical_status ?? null} />
        <StageBadge status={candidate.workflow_state?.research_status ?? null} />
        <Badge variant="neutral">as_of {formatShanghaiTime(candidate.as_of)}</Badge>
      </div>

      <section aria-labelledby="snapshot-evidence-title">
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <SectionLabel tone="raw">Raw market data</SectionLabel>
              <h2 id="snapshot-evidence-title" className="mt-2 text-base font-semibold">
                Snapshot evidence
              </h2>
            </div>
            <p className="font-mono text-sm font-semibold text-rose-500">
              {formatPercent(snapshot.pct_change)}
            </p>
          </CardHeader>
          <CardContent>
            <FeatureGrid>
              <Field label="Price" value={formatNumber(snapshot.price)} />
              <Field label="Absolute change" value={formatNumber(snapshot.absolute_change)} />
              <Field label="Previous close" value={formatNumber(snapshot.previous_close)} />
              <Field label="Open" value={formatNumber(snapshot.open)} />
              <Field label="High" value={formatNumber(snapshot.high)} />
              <Field label="Low" value={formatNumber(snapshot.low)} />
              <Field label="Volume" value={formatInteger(snapshot.volume)} />
              <Field label="Turnover amount" value={formatCompactMoney(snapshot.amount)} />
              <Field
                label="Turnover rate"
                value={
                  snapshot.turnover_rate == null ? '—' : `${formatNumber(snapshot.turnover_rate)}%`
                }
              />
              <Field
                label="Amplitude"
                value={snapshot.amplitude == null ? '—' : `${formatNumber(snapshot.amplitude)}%`}
              />
              <Field label="Volume ratio" value={formatNumber(snapshot.volume_ratio)} />
              <Field
                label="Float market cap"
                value={formatCompactMoney(snapshot.float_market_cap)}
              />
            </FeatureGrid>
            <div className="mt-5 grid gap-3 border-t border-[var(--border)] pt-5 text-xs md:grid-cols-2 xl:grid-cols-4">
              <Field label="Provider" value={candidate.snapshot_evidence.provider} />
              <Field
                label="Intended snapshot"
                value={formatShanghaiTime(candidate.snapshot_evidence.intended_snapshot_time)}
              />
              <Field
                label="Actual fetch finished"
                value={formatShanghaiTime(candidate.snapshot_evidence.actual_fetch_finished_at)}
              />
              <Field label="Rule version" value={candidate.screening_rule_version} mono />
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="mt-5" aria-labelledby="deterministic-title">
        <Card>
          <CardHeader className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <SectionLabel tone="deterministic">Deterministic calculations</SectionLabel>
              <h2 id="deterministic-title" className="mt-2 text-base font-semibold">
                Intraday feature analysis
              </h2>
            </div>
            {intraday && (
              <Badge variant={intraday.data_quality.status === 'good' ? 'ready' : 'warning'}>
                {intraday.data_quality.status} data
              </Badge>
            )}
          </CardHeader>
          <CardContent>
            {!intraday ? (
              <EmptyPanel
                title="No technical artifact"
                description="No point-in-time intraday feature artifact has been persisted for this candidate."
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
                    No point-in-time bar series was persisted for this analysis.
                  </div>
                )}
                <div className="grid gap-5 xl:grid-cols-2">
                  <FeatureSection title="Price behavior">
                    <Field
                      label="Previous 5-minute return"
                      value={formatPercent(intraday.price.previous_5m_return_pct)}
                    />
                    <Field
                      label="Previous 15-minute return"
                      value={formatPercent(intraday.price.previous_15m_return_pct)}
                    />
                    <Field
                      label="Previous 30-minute return"
                      value={formatPercent(intraday.price.previous_30m_return_pct)}
                    />
                    <Field
                      label="Return since open"
                      value={formatPercent(intraday.price.return_since_open_pct)}
                    />
                    <Field
                      label="Distance from high"
                      value={formatPercent(intraday.price.distance_from_intraday_high_pct)}
                    />
                    <Field
                      label="Distance from low"
                      value={formatPercent(intraday.price.distance_from_intraday_low_pct)}
                    />
                    <Field
                      label="Normalized position"
                      value={formatNumber(intraday.price.normalized_intraday_position)}
                    />
                    <Field
                      label="Drawdown from high"
                      value={formatPercent(intraday.price.drawdown_from_intraday_high_pct)}
                    />
                  </FeatureSection>
                  <FeatureSection title="Volume / value behavior">
                    <Field
                      label="Recent 5-minute volume"
                      value={formatInteger(intraday.volume.recent_5m_volume)}
                    />
                    <Field
                      label="Previous comparable volume"
                      value={formatInteger(intraday.volume.previous_comparable_5m_volume)}
                    />
                    <Field
                      label="Volume acceleration"
                      value={formatNumber(intraday.volume.recent_volume_acceleration_ratio)}
                    />
                    <Field
                      label="Recent turnover amount"
                      value={formatCompactMoney(intraday.volume.recent_turnover_amount)}
                    />
                    <Field label="VWAP" value={formatNumber(intraday.volume.vwap, 3)} />
                    <Field
                      label="Distance from VWAP"
                      value={formatPercent(intraday.volume.distance_from_vwap_pct)}
                    />
                  </FeatureSection>
                </div>
                <FeatureSection title="Deterministic path descriptions">
                  {Object.entries(intraday.path).map(([key, value]) => (
                    <Field
                      key={key}
                      label={humanize(key)}
                      value={value == null ? 'Not evaluable' : value ? 'Detected' : 'Not detected'}
                    />
                  ))}
                </FeatureSection>
                <div className="grid gap-3 text-xs md:grid-cols-2 xl:grid-cols-4">
                  <Field
                    label="Analysis as_of"
                    value={formatShanghaiTime(intraday.analysis_as_of)}
                  />
                  <Field label="Calculation version" value={intraday.calculation_version} mono />
                  <Field
                    label="Feature schema"
                    value={`v${String(intraday.feature_schema_version)}`}
                    mono
                  />
                  <Field
                    label="Bars used / future excluded"
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
              <SectionLabel tone="ai">AI interpretation</SectionLabel>
              <h2 id="ai-research-title" className="mt-2 text-base font-semibold">
                Evidence-backed web research
              </h2>
            </div>
            {research && (
              <div className="text-right">
                <Badge variant={research.evidence_quality === 'insufficient' ? 'warning' : 'ready'}>
                  {research.evidence_quality} evidence
                </Badge>
                <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                  Confidence {formatNumber(research.confidence * 100, 0)}%
                </p>
              </div>
            )}
          </CardHeader>
          <CardContent>
            {!research ? (
              <EmptyPanel
                title="No AI research artifact"
                description="No successful or explicit no-evidence research artifact is available. Deterministic evidence above remains independent."
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
                    title="Verified facts"
                    claims={research.verified_facts}
                    empty="No verified facts at the cutoff."
                  />
                  <ClaimSection
                    title="Likely drivers"
                    claims={research.likely_drivers}
                    empty="No evidence-backed drivers were identified."
                  />
                  <ClaimSection title="Company context" claims={research.company_context} />
                  <ClaimSection title="Sector context" claims={research.sector_context} />
                  <ClaimSection title="Market context" claims={research.market_context} />
                  <ClaimSection title="Positive factors" claims={research.positive_factors} />
                  <ClaimSection title="Risk factors" claims={research.risk_factors} />
                  <TextList title="Unresolved questions" values={research.unresolved_questions} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold">Research sources</h3>
                  {research.sources.length === 0 ? (
                    <p className="mt-2 text-sm text-[var(--text-muted)]">
                      No usable web source was persisted.
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
                              {source.publisher_domain} · published{' '}
                              {formatShanghaiTime(source.published_at)} ·{' '}
                              {source.publication_timestamp_status}
                            </p>
                            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[var(--text-subtle)]">
                              <Badge
                                variant={
                                  source.availability_at_as_of === 'available_at_as_of'
                                    ? 'ready'
                                    : 'warning'
                                }
                              >
                                {humanize(source.availability_at_as_of)}
                              </Badge>
                              <span>retrieved {formatShanghaiTime(source.retrieved_at)}</span>
                              <span>
                                {String(source.relationship_claim_ids.length)} linked claim(s)
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
                  <Field
                    label="Research as_of"
                    value={formatShanghaiTime(research.analysis_as_of)}
                  />
                  <Field label="Prompt version" value={research.prompt_version} mono />
                  <Field label="Model" value={research.model_identifier} mono />
                  <Field label="Created" value={formatShanghaiTime(research.created_at)} />
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
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
  empty = 'No persisted claims.',
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
                {claim.classification.replaceAll('_', ' ')}
              </Badge>
              <p className="mt-2">{claim.statement}</p>
              <p className="mt-1 text-[10px] text-[var(--text-subtle)]">
                {String(claim.source_ids.length)} linked source(s)
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
        <p className="mt-2 text-sm text-[var(--text-muted)]">None persisted.</p>
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

function humanize(value: string) {
  return value.replaceAll('_', ' ');
}
