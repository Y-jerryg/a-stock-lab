import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense, useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { readRunDetails } from './api';
import { marketTime, percent } from './format';
import './trend.css';

const DailyChart = lazy(async () => {
  const module = await import('./DailyCandlestickChart');
  return { default: module.DailyCandlestickChart };
});
const number = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const compact = (value: number, unit: string) =>
  value >= 100000000
    ? `${number(value / 100000000)} 亿${unit}`
    : value >= 10000
      ? `${number(value / 10000)} 万${unit}`
      : `${number(value)} ${unit}`;
const providerNames: Record<string, string> = {
  sina_daily_qfq: '新浪日线',
  eastmoney_daily_qfq: '东方财富日线',
};

function Metrics({ items }: { items: [string, string | number][] }) {
  return (
    <dl className="trend-detail-metrics">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function TrendStockDetailPage() {
  const { runId = '', symbol = '' } = useParams();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [runId, symbol]);
  const validIdentity =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(runId) &&
    /^\d{6}$/.test(symbol);
  const query = useQuery({
    queryKey: ['trend-details', runId],
    queryFn: () => readRunDetails(runId),
    enabled: validIdentity,
    staleTime: Infinity,
  });
  const back = (
    <Link className="trend-back" to={validIdentity ? `/trend-radar?run=${runId}` : '/trend-radar'}>
      ← 返回本次扫描结果
    </Link>
  );
  if (!validIdentity)
    return (
      <section className="trend-page">
        {back}
        <p role="alert">股票详情地址无效。</p>
      </section>
    );
  if (query.isPending)
    return (
      <section className="trend-page">
        {back}
        <p role="status">正在加载股票日线详情……</p>
      </section>
    );
  if (query.isError)
    return (
      <section className="trend-page">
        {back}
        <p role="alert">股票详情加载失败，请刷新页面重试。</p>
      </section>
    );
  if (!query.data)
    return (
      <section className="trend-page">
        {back}
        <h1>此历史扫描尚未导出 K 线详情</h1>
        <p>请在电脑端点击“重新导出结果”；公网网站还需要重新发布。已有扫描数据无需重新抓取。</p>
      </section>
    );
  const detail = query.data.details.find((item) => item.candidate.symbol === symbol);
  if (!detail)
    return (
      <section className="trend-page">
        {back}
        <p role="alert">这只股票不在本次扫描的候选结果中。</p>
      </section>
    );
  const { candidate: stock, bars } = detail;
  const run = query.data.run;
  const config = run.payload.configuration_snapshot;
  const latest = bars.at(-1);
  const previous = bars.at(-2);
  const change = latest && previous ? latest.close - previous.close : null;
  const changePct = latest && previous ? (latest.close / previous.close - 1) * 100 : null;
  const changeClass = change === null || change === 0 ? '' : change > 0 ? 'trend-up' : 'trend-down';
  return (
    <section className="trend-page trend-detail-page">
      {back}
      <header className="trend-heading">
        <div>
          <p className="trend-eyebrow">趋势雷达 / 股票详情 / {run.trade_date}</p>
          <h1>
            {stock.name} <span className="trend-symbol">{symbol}</span>
          </h1>
          <p>
            热度排名 #{stock.heat_rank} · {stock.trend_days} 日下降趋势 ·{' '}
            {stock.is_strong_volume_contraction ? '强缩量' : '普通成交量'}
          </p>
        </div>
        {latest && (
          <div className={`trend-quote ${changeClass}`}>
            <strong>{latest.close.toFixed(2)}</strong>
            <span>
              {change !== null ? `${change > 0 ? '+' : ''}${change.toFixed(2)}` : '—'} /{' '}
              {changePct !== null ? `${changePct > 0 ? '+' : ''}${percent(changePct)}` : '—'}
            </span>
            <small>{latest.trade_date} 收盘 · 前复权</small>
          </div>
        )}
      </header>
      {run.status === 'completed_with_warnings' && (
        <p className="trend-notice">本次扫描部分股票数据获取失败，当前股票已成功处理。</p>
      )}
      {latest && (
        <div className="trend-detail-panel">
          <Metrics
            items={[
              ['开盘价', latest.open.toFixed(2)],
              ['最高价', latest.high.toFixed(2)],
              ['最低价', latest.low.toFixed(2)],
              ['收盘价', latest.close.toFixed(2)],
              ['成交量', compact(latest.volume, '手')],
              ['成交额', compact(latest.amount, '元')],
            ]}
          />
        </div>
      )}
      <section className="trend-detail-panel" aria-labelledby="trend-chart-title">
        <div className="trend-panel-heading">
          <div>
            <h2 id="trend-chart-title">日 K 线与成交量</h2>
            <p>前复权 · 红涨绿跌 · MA5 / MA10 / MA20</p>
          </div>
          <span className="trend-badge">{bars.length} 个已保存交易日</span>
        </div>
        {bars.length ? (
          <>
            <Suspense
              fallback={
                <p role="status" className="trend-chart-loading">
                  正在加载 K 线图……
                </p>
              }
            >
              <DailyChart
                bars={bars}
                symbol={symbol}
                trendStart={stock.trend_start_date}
                trendEnd={stock.trend_end_date}
              />
            </Suspense>
            <p className="trend-chart-hint">
              拖动底部滑块或在图中缩放，查看不同日期；阴影标记本次入选的趋势区间。
            </p>
          </>
        ) : (
          <p>本次历史扫描未保存日线明细，无法绘制 K 线图。筛选指标保留如下。</p>
        )}
      </section>
      <div className="trend-detail-columns">
        <section className="trend-detail-panel">
          <h2>为什么入选</h2>
          <p className="trend-chart-hint">
            {stock.trend_start_date} 至 {stock.trend_end_date}
          </p>
          <Metrics
            items={[
              ['趋势天数', `${String(stock.trend_days)} 日`],
              ['区间涨跌幅', percent(stock.trend_return_pct)],
              [
                '趋势起点收盘',
                bars.find((bar) => bar.trade_date === stock.trend_start_date)?.close.toFixed(2) ??
                  '—',
              ],
              ['趋势终点收盘', latest?.close.toFixed(2) ?? '—'],
              [
                '期间回调次数',
                `${String(stock.pullback_days)} / 最多 ${String(config.max_pullback_days)} 次`,
              ],
              [
                '最大单次回调',
                `${percent(stock.max_pullback_pct)} / 上限 ${percent(config.max_single_pullback_pct)}`,
              ],
              ['价格趋势斜率', stock.trend_slope.toFixed(4)],
              ['关注指数排名', `#${String(stock.heat_rank)}`],
            ]}
          />
        </section>
        <section className="trend-detail-panel">
          <h2>成交量与成交额对比</h2>
          <p className="trend-chart-hint">
            趋势期与紧邻此前 {config.baseline_volume_days} 个交易日比较
          </p>
          <Metrics
            items={[
              ['趋势期日均成交量', compact(stock.trend_volume_avg, '手')],
              ['基准期日均成交量', compact(stock.baseline_volume_avg, '手')],
              ['成交量比例', percent(stock.volume_ratio, true)],
              ['强缩量阈值', `≤ ${percent(config.strong_volume_ratio, true)}`],
              ['趋势期日均成交额', compact(stock.trend_amount_avg, '元')],
              ['基准期日均成交额', compact(stock.baseline_amount_avg, '元')],
              ['成交额比例', percent(stock.amount_ratio, true)],
              ['判定结果', stock.is_strong_volume_contraction ? '强缩量' : '未达到强缩量阈值'],
            ]}
          />
        </section>
      </div>
      <details className="trend-detail-panel trend-daily-table">
        <summary>查看每日行情数据（{bars.length} 条）</summary>
        {bars.length ? (
          <div
            className="trend-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="每日行情数据表，可横向滚动"
          >
            <table>
              <caption>本次扫描保存的前复权日线，按日期从近到远排列</caption>
              <thead>
                <tr>
                  {['日期', '开盘', '最高', '最低', '收盘', '成交量（手）', '成交额（元）'].map(
                    (label) => (
                      <th key={label} scope="col">
                        {label}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {[...bars].reverse().map((bar) => (
                  <tr
                    key={bar.trade_date}
                    className={bar.trade_date >= stock.trend_start_date ? 'trend-window-row' : ''}
                  >
                    <th scope="row">{bar.trade_date}</th>
                    <td>{bar.open.toFixed(2)}</td>
                    <td>{bar.high.toFixed(2)}</td>
                    <td>{bar.low.toFixed(2)}</td>
                    <td>{bar.close.toFixed(2)}</td>
                    <td>{number(bar.volume)}</td>
                    <td>{number(bar.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>没有已保存的日线数据。</p>
        )}
      </details>
      <footer className="trend-detail-panel trend-evidence">
        <h2>数据日期与来源</h2>
        <p>
          行情截止：{run.trade_date} · 扫描数据截止：{marketTime(run.payload.data_as_of)}
        </p>
        <p>
          日线来源：
          {[...new Set(bars.map((bar) => providerNames[bar.source] ?? bar.source))].join('、') ||
            '暂无记录'}{' '}
          · 成交量单位：手（100 股） · 成交额单位：元
        </p>
        <p>
          图表和指标均来自这次扫描保存的数据。切换历史扫描时会展示当时的数据，打开详情不会重新抓取行情。
        </p>
      </footer>
    </section>
  );
}
