import { useQuery } from '@tanstack/react-query';
import { lazy, Suspense } from 'react';
import { apiClient } from '../../lib/api/client';
import type { DailyBar } from '../../components/dailyChartData';
import { Card, CardContent, CardHeader } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { formatShanghaiTime } from './format';

const Chart = lazy(async () => {
  const module = await import('../../components/DailyCandlestickChart');
  return { default: module.DailyCandlestickChart };
});
interface DailyChartResponse {
  symbol: string;
  cutoff: string;
  fetched_at: string;
  bars: DailyBar[];
}
export function DailyChartPanel({ candidateId, symbol }: { candidateId: string; symbol: string }) {
  const query = useQuery({
    queryKey: ['tail-daily-chart', candidateId],
    queryFn: () =>
      apiClient.get<DailyChartResponse>(`/api/v1/tail-radar/candidates/${candidateId}/daily-chart`),
    staleTime: 86400000,
    retry: false,
  });
  return (
    <section className="mt-5" aria-labelledby="daily-chart-title">
      <Card>
        <CardHeader>
          <h2 id="daily-chart-title" className="text-base font-semibold">
            日 K 线与成交量
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            前复权 · MA5 / MA10 / MA20 · 成交量（手）· 红涨绿跌
          </p>
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-xs text-[var(--text-muted)]">
            展示快照日期之前的已收盘日线，不包含快照当天尚未完成的日
            K。行情为补充参考，按采集时的复权数据展示，不参与原快照筛选或 AI 证据计算。
          </p>
          {query.isPending ? (
            <p role="status">正在加载日 K 线，首次读取可能需要数十秒，之后复用本地缓存……</p>
          ) : query.isError ? (
            <div role="alert">
              <p>{query.error.message}</p>
              <Button
                variant="outline"
                onClick={() => {
                  void query.refetch();
                }}
              >
                重新加载日 K
              </Button>
            </div>
          ) : query.data.bars.length ? (
            <>
              <Suspense fallback={<p>正在绘制日 K 图……</p>}>
                <Chart bars={query.data.bars} symbol={symbol} />
              </Suspense>
              <p className="mt-3 text-xs text-[var(--text-muted)]">
                行情截止 {query.data.bars.at(-1)?.trade_date} · {query.data.bars.length} 个交易日 ·
                采集于 {formatShanghaiTime(query.data.fetched_at)}
                。可缩放，悬停查看开高低收及成交量。
              </p>
            </>
          ) : (
            <p>该日期范围暂无可用日线数据。</p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
