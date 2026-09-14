import { BarChart, CandlestickChart, LineChart } from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
} from 'echarts/components';
import { init, use as registerECharts, type EChartsCoreOption } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';
import type { DailyBar } from './api';
import { movingAverage } from './chartData';

registerECharts([
  CandlestickChart,
  BarChart,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export function DailyCandlestickChart({
  bars,
  symbol,
  trendStart,
  trendEnd,
}: {
  bars: DailyBar[];
  symbol: string;
  trendStart: string;
  trendEnd: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !bars.length) return;
    const chart = init(element.current, undefined, { renderer: 'canvas' });
    const averages = [5, 10, 20].map((days) => movingAverage(bars, days));
    const draw = () => {
      const styles = getComputedStyle(document.documentElement);
      const muted = styles.getPropertyValue('--text-muted').trim();
      const border = styles.getPropertyValue('--border').trim();
      const option: EChartsCoreOption = {
        animation: false,
        color: ['#f1b44c', '#789bff', '#cd86d9'],
        legend: { data: ['MA5', 'MA10', 'MA20'], top: 4, textStyle: { color: muted } },
        grid: [
          { left: 64, right: 20, top: 42, height: '55%' },
          { left: 64, right: 20, top: '72%', height: '14%' },
        ],
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
              bar.trade_date,
              `开 ${bar.open.toFixed(2)}   收 ${bar.close.toFixed(2)}`,
              `高 ${bar.high.toFixed(2)}   低 ${bar.low.toFixed(2)}`,
              `成交量 ${bar.volume.toLocaleString('zh-CN')} 手`,
              `成交额 ${(bar.amount / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 })} 万元`,
              ...averages.map(
                (values, i) => `MA${String([5, 10, 20][i])} ${values[index]?.toFixed(2) ?? '—'}`,
              ),
            ].join('\n');
          },
        },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        xAxis: [0, 1].map((index) => ({
          type: 'category',
          gridIndex: index,
          data: bars.map((bar) => bar.trade_date),
          boundaryGap: true,
          axisLine: { lineStyle: { color: border } },
          axisTick: { show: false },
          axisLabel: {
            show: index === 1,
            color: muted,
            formatter: (value: string) => value.slice(5),
          },
        })),
        yAxis: [
          {
            scale: true,
            name: '元',
            axisLabel: { color: muted },
            nameTextStyle: { color: muted },
            splitLine: { lineStyle: { color: border, type: 'dashed' } },
          },
          {
            gridIndex: 1,
            name: '万手',
            splitNumber: 2,
            nameTextStyle: { color: muted },
            axisLabel: { color: muted, hideOverlap: true },
            splitLine: { show: false },
          },
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
          {
            type: 'slider',
            xAxisIndex: [0, 1],
            bottom: 4,
            height: 22,
            borderColor: border,
            textStyle: { color: muted },
            showDataShadow: false,
          },
        ],
        series: [
          {
            name: '日 K 线',
            type: 'candlestick',
            data: bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
            itemStyle: {
              color: '#ef5350',
              color0: '#15b887',
              borderColor: '#ef5350',
              borderColor0: '#15b887',
            },
            markArea: {
              silent: true,
              itemStyle: { color: 'rgba(120,155,255,0.12)' },
              label: { color: muted },
              data: [[{ name: '入选趋势区间', xAxis: trendStart }, { xAxis: trendEnd }]],
            },
          },
          ...averages.map((values, index) => ({
            name: `MA${String([5, 10, 20][index])}`,
            type: 'line',
            data: values,
            showSymbol: false,
            lineStyle: { width: 1.4 },
            connectNulls: false,
          })),
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
      chart.setOption(option);
    };
    draw();
    const size = new ResizeObserver(() => {
      chart.resize();
    });
    size.observe(element.current);
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme', 'style'],
    });
    return () => {
      theme.disconnect();
      size.disconnect();
      chart.dispose();
    };
  }, [bars, symbol, trendStart, trendEnd]);
  return (
    <div
      className="trend-daily-chart"
      ref={element}
      role="img"
      aria-label={`${symbol} 前复权日 K 线、均线与成交量图`}
    />
  );
}
