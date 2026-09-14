import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { init, use as registerECharts, type ECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';

import type { IntradayBar } from './api';

registerECharts([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export function IntradayChart({ bars, symbol }: { bars: IntradayBar[]; symbol: string }) {
  const elementRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!elementRef.current || bars.length === 0) return;
    const styles = getComputedStyle(document.documentElement);
    const chart: ECharts = init(elementRef.current, undefined, { renderer: 'canvas' });
    chart.setOption({
      animation: false,
      grid: { top: 24, right: 18, bottom: 36, left: 58 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: unknown) =>
          typeof value === 'number' ? value.toFixed(3) : String(value),
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: bars.map((bar) =>
          new Intl.DateTimeFormat('zh-CN', {
            timeZone: 'Asia/Shanghai',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          }).format(new Date(bar.ended_at)),
        ),
        axisLine: { lineStyle: { color: styles.getPropertyValue('--border-strong') } },
        axisLabel: { color: styles.getPropertyValue('--text-subtle'), hideOverlap: true },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: styles.getPropertyValue('--border'), type: 'dashed' } },
        axisLabel: { color: styles.getPropertyValue('--text-subtle') },
      },
      series: [
        {
          name: '收盘价',
          type: 'line',
          data: bars.map((bar) => bar.close),
          showSymbol: false,
          lineStyle: { width: 2, color: styles.getPropertyValue('--accent') },
          areaStyle: { color: 'rgba(47, 128, 191, 0.08)' },
        },
      ],
    });
    const observer = new ResizeObserver(() => {
      chart.resize();
    });
    observer.observe(elementRef.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [bars, symbol]);

  if (bars.length === 0) {
    return (
      <div className="grid h-72 place-items-center rounded-md bg-[var(--surface-muted)] text-sm text-[var(--text-muted)]">
        本次分析没有保存可用的时点分时数据序列。
      </div>
    );
  }
  return (
    <div ref={elementRef} className="h-80 w-full" role="img" aria-label={`${symbol} 日内分时图`} />
  );
}
