import { BarChart, CandlestickChart } from 'echarts/charts';
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { init, use as registerECharts } from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useEffect, useRef } from 'react';

import type { IntradayBar } from './api';
import { intradayChartOption } from './intradayChartData';

registerECharts([
  CandlestickChart,
  BarChart,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
]);

export function IntradayChart({ bars, symbol }: { bars: IntradayBar[]; symbol: string }) {
  const elementRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!elementRef.current || !bars.length) return;
    const chart = init(elementRef.current, undefined, { renderer: 'canvas' });
    const draw = () => {
      const styles = getComputedStyle(document.documentElement);
      chart.setOption(
        intradayChartOption(bars, {
          muted: styles.getPropertyValue('--text-muted').trim(),
          border: styles.getPropertyValue('--border').trim(),
        }),
      );
    };
    draw();
    const size = new ResizeObserver(() => {
      chart.resize();
    });
    size.observe(elementRef.current);
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
  }, [bars, symbol]);

  if (!bars.length) return <p>本次分析没有保存可用的时点分时数据序列。</p>;
  return (
    <div
      ref={elementRef}
      className="h-[440px] w-full"
      role="img"
      aria-label={`${symbol} 5 分钟 K 线与成交量图`}
    />
  );
}
