export interface DailyBar {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export function movingAverage(bars: DailyBar[], days: number): (number | null)[] {
  return bars.map((_, index) =>
    index + 1 < days
      ? null
      : bars.slice(index + 1 - days, index + 1).reduce((sum, bar) => sum + bar.close, 0) / days,
  );
}
