import type { DailyBar } from './api';

export function movingAverage(bars: DailyBar[], days: number): (number | null)[] {
  return bars.map((_, index) =>
    index + 1 < days
      ? null
      : bars.slice(index + 1 - days, index + 1).reduce((sum, bar) => sum + bar.close, 0) / days,
  );
}
