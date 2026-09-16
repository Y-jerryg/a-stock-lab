import { describe, expect, it } from 'vitest';
import type { IntradayBar } from './api';
import { intradayChartOption } from './intradayChartData';

describe('saved Tail Radar candlesticks', () => {
  it('maps OHLC correctly, preserves zero volume, and uses shares with Shanghai bar-end times', () => {
    const bar: IntradayBar = {
      symbol: '600000',
      interval_minutes: 5,
      ended_at: '2026-09-14T01:35:00Z',
      open: 10,
      close: 11,
      low: 9,
      high: 12,
      volume: 12500,
      amount: 130000,
      provider: 'fixture',
      provider_timestamp: null,
      fetched_at: '2026-09-14T06:30:00Z',
    };
    const option = intradayChartOption(
      [bar, { ...bar, ended_at: '2026-09-14T01:40:00Z', open: 11, close: 10, volume: 0 }],
      { muted: '#aaa', border: '#555' },
    );
    expect(option.xAxis).toEqual(
      expect.arrayContaining([expect.objectContaining({ data: ['09:35', '09:40'] })]),
    );
    expect(option.series).toEqual([
      expect.objectContaining({
        type: 'candlestick',
        data: [
          [10, 11, 9, 12],
          [11, 10, 9, 12],
        ],
      }),
      expect.objectContaining({
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: [
          { value: 1.25, itemStyle: { color: '#ef5350' } },
          { value: 0, itemStyle: { color: '#15b887' } },
        ],
      }),
    ]);
    const tooltip = option.tooltip as { formatter: (values: unknown) => string };
    expect(tooltip.formatter([{ dataIndex: 0 }])).toContain('12,500 股');
    expect(tooltip.formatter([{ dataIndex: 0 }])).toContain('09:35（北京时间）');
  });
});
