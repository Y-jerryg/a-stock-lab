import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { text } from '../../locales';
import { readDashboard, readResults, type Result } from './api';
import { marketTime, percent } from './format';
import './trend.css';

const t = text.trend;

function StockCard({ stock, runId }: { stock: Result; runId: string }) {
  const detailPath = `/trend-radar/runs/${runId}/stocks/${stock.symbol}`;
  const metrics = [
    [t.rank, `#${String(stock.heat_rank)}`],
    [t.days, t.trendLabel(stock.trend_days)],
    [t.decline, percent(stock.trend_return_pct)],
    [t.pullbacks, stock.pullback_days],
    [t.maxPullback, percent(stock.max_pullback_pct)],
    [t.volume, percent(stock.volume_ratio, true)],
    [t.amount, percent(stock.amount_ratio, true)],
  ];
  return (
    <article className={`trend-stock ${stock.is_strong_volume_contraction ? 'trend-strong' : ''}`}>
      <header>
        <div>
          <h2>
            <Link className="trend-stock-name" to={detailPath}>
              {stock.name}
            </Link>
          </h2>
          <span>{stock.symbol}</span>
        </div>
        <b className="trend-badge">{t.status[stock.highlight_level]}</b>
      </header>
      <dl>
        {metrics.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <Link className="trend-detail-link" to={detailPath}>
        查看 K 线与数据 <span aria-hidden="true">→</span>
      </Link>
      <details>
        <summary>{t.detail}</summary>
        <dl>
          {[
            [t.start, stock.trend_start_date],
            [t.end, stock.trend_end_date],
            [t.slope, stock.trend_slope.toFixed(4)],
            [t.volumeAverage, stock.trend_volume_avg.toFixed(0)],
            [t.baselineVolume, stock.baseline_volume_avg.toFixed(0)],
            [t.amountAverage, stock.trend_amount_avg.toFixed(0)],
            [t.baselineAmount, stock.baseline_amount_avg.toFixed(0)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </article>
  );
}

export function TrendRadarPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.get('run') ?? '';
  const select = (value: string) => {
    setSearchParams(value ? { run: value } : {});
  };
  const [strong, setStrong] = useState(false);
  const [days, setDays] = useState(0);
  const dashboard = useQuery({
    queryKey: ['trend-dashboard'],
    queryFn: readDashboard,
    refetchInterval: 5000,
  });
  const run = selected
    ? dashboard.data?.attempts.find(
        (item) =>
          item.id === selected && ['success', 'completed_with_warnings'].includes(item.status),
      )
    : dashboard.data?.latest;
  const results = useQuery({
    queryKey: ['trend-results', run?.id],
    queryFn: () => readResults(run?.id ?? ''),
    enabled: !!run,
  });
  const filtered =
    results.data?.filter(
      (row) => (!strong || row.is_strong_volume_contraction) && (!days || row.trend_days === days),
    ) ?? [];
  const config = run?.payload.configuration_snapshot;
  return (
    <section className="trend-page">
      <header className="trend-heading">
        <div>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>
      </header>
      {dashboard.isPending ? (
        <p role="status">{t.loading}</p>
      ) : dashboard.isError ? (
        <p role="alert">{t.error}</p>
      ) : (
        <>
          {dashboard.data.attempts[0]?.status === 'failed' && (
            <p className="trend-notice">{run ? t.previous : t.failedWithoutResults}</p>
          )}
          {run?.status === 'completed_with_warnings' && (
            <p className="trend-notice" role="status">
              {t.partial}
            </p>
          )}
          {!!run?.payload.requested_count && (
            <p>
              {t.coverage(
                run.payload.requested_count,
                run.payload.successful_count ?? 0,
                run.payload.failed_count ?? 0,
              )}
            </p>
          )}
          {!!run?.payload.failed_symbols?.length && (
            <details className="trend-notice">
              <summary>{t.failedStocks}</summary>
              <ul>
                {run.payload.failed_symbols.map((stock) => (
                  <li key={stock.symbol}>
                    {stock.symbol} {stock.name} · {stock.error_code}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <div className="trend-summary">
            {[
              [t.dataDate, run?.trade_date ?? t.missing],
              [t.heatCount, run?.payload.heat_universe_count ?? '—'],
              [t.candidates, run?.payload.candidate_count ?? '—'],
              [t.strongCount, run?.payload.strong_contraction_count ?? '—'],
            ].map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <p>
            {t.updated}：{marketTime(run?.payload.data_as_of)}
          </p>
          <p>
            {t.attempt}：{marketTime(dashboard.data.attempts[0]?.started_at)} ·{' '}
            {dashboard.data.attempts[0] ? t.status[dashboard.data.attempts[0].status] : t.missing}
          </p>
          {dashboard.data.attempts[0] &&
            dashboard.data.attempts[0].id !== run?.id &&
            !!dashboard.data.attempts[0].payload.requested_count && (
              <p>
                {t.attemptCoverage(
                  dashboard.data.attempts[0].payload.successful_count ?? 0,
                  dashboard.data.attempts[0].payload.failed_count ?? 0,
                  dashboard.data.attempts[0].payload.requested_count ?? 0,
                )}
              </p>
            )}
          <div className="trend-filters">
            <label>
              {t.history}
              <select
                value={selected}
                onChange={(event) => {
                  select(event.target.value);
                }}
              >
                <option value="">{t.latest}</option>
                {dashboard.data.attempts
                  .filter((item) => ['success', 'completed_with_warnings'].includes(item.status))
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {marketTime(item.started_at)} · {t.status[item.trigger_type]}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              {t.filter}
              <select
                value={strong ? 'strong' : 'all'}
                onChange={(event) => {
                  setStrong(event.target.value === 'strong');
                }}
              >
                <option value="all">{t.all}</option>
                <option value="strong">{t.onlyStrong}</option>
              </select>
            </label>
            <label>
              {t.days}
              <select
                value={days}
                onChange={(event) => {
                  setDays(Number(event.target.value));
                }}
              >
                <option value={0}>{t.all}</option>
                {[7, 8, 9].map((day) => (
                  <option key={day} value={day}>
                    {t.dayFilter(day)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!run ? (
            <p>{t.empty}</p>
          ) : results.isPending ? (
            <p role="status">{t.loading}</p>
          ) : results.isError ? (
            <p role="alert">{t.error}</p>
          ) : (
            <>
              {!!results.data.length &&
                !results.data.some((row) => row.is_strong_volume_contraction) && (
                  <p>{t.noStrong}</p>
                )}
              {!filtered.length && <p>{t.noCandidates}</p>}
              <div className="trend-grid">
                {filtered.map((stock) => (
                  <StockCard key={stock.symbol} stock={stock} runId={run.id} />
                ))}
              </div>
            </>
          )}
          {config && (
            <aside className="trend-explanation">
              <h2>{t.rules}</h2>
              <p>
                {t.explanation(
                  config.top_n,
                  config.min_days,
                  config.max_days,
                  config.max_pullback_days,
                  config.max_single_pullback_pct,
                  config.baseline_volume_days,
                  config.strong_volume_ratio,
                )}
              </p>
              <p>
                {t.heatSource}。{t.completedBars}
              </p>
            </aside>
          )}
        </>
      )}
    </section>
  );
}
