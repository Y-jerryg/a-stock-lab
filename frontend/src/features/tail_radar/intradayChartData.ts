import type { EChartsCoreOption } from 'echarts/core';
import type { IntradayBar } from './api';

export function intradayChartOption(
  bars: IntradayBar[],
  colors: { muted: string; border: string },
): EChartsCoreOption {
  const time = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const labels = bars.map((bar) => time.format(new Date(bar.ended_at)));
  return {
    animation: false,
    grid: [
      { top: 28, right: 20, left: 64, height: '51%' },
      { top: '69%', right: 20, left: 64, height: '16%' },
    ],
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      confine: true,
      axisPointer: { type: 'cross' },
      formatter: (params: unknown) => {
        const point = Array.isArray(params) ? (params[0] as { dataIndex?: number }) : undefined;
        const index = point?.dataIndex ?? -1;
        const bar = bars[index];
        if (!bar) return '';
        return [
          `${labels[index] ?? ''}（北京时间）`,
          `开 ${bar.open.toFixed(3)}  收 ${bar.close.toFixed(3)}`,
          `高 ${bar.high.toFixed(3)}  低 ${bar.low.toFixed(3)}`,
          `成交量 ${bar.volume.toLocaleString('zh-CN')} 股`,
          `成交额 ${bar.amount.toLocaleString('zh-CN')} 元`,
        ].join('\n');
      },
    },
    xAxis: [0, 1].map((index) => ({
      type: 'category',
      gridIndex: index,
      data: labels,
      boundaryGap: true,
      axisLabel: { show: index === 1, color: colors.muted, hideOverlap: true },
      axisLine: { lineStyle: { color: colors.border } },
      axisTick: { show: false },
    })),
    yAxis: [
      {
        scale: true,
        name: '价格（元）',
        axisLabel: { color: colors.muted },
        nameTextStyle: { color: colors.muted },
        splitLine: { lineStyle: { color: colors.border, type: 'dashed' } },
      },
      {
        gridIndex: 1,
        name: '成交量（万股）',
        min: 0,
        splitNumber: 2,
        axisLabel: { color: colors.muted },
        nameTextStyle: { color: colors.muted },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 4,
        height: 20,
        showDataShadow: false,
        borderColor: colors.border,
        textStyle: { color: colors.muted },
      },
    ],
    series: [
      {
        name: '5 分钟 K 线',
        type: 'candlestick',
        data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
        itemStyle: {
          color: '#ef5350',
          color0: '#15b887',
          borderColor: '#ef5350',
          borderColor0: '#15b887',
        },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: bars.map((bar) => ({
          value: bar.volume / 10000,
          itemStyle: { color: bar.close >= bar.open ? '#ef5350' : '#15b887' },
        })),
      },
    ],
  };
}
