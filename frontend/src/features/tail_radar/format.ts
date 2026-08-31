const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
const integerFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 });

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null) return '—';
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${value > 0 ? '+' : ''}${formatNumber(value)}%`;
}

export function formatInteger(value: number | null | undefined): string {
  return value == null ? '—' : integerFormatter.format(value);
}

export function formatCompactMoney(value: number | null | undefined): string {
  if (value == null) return '—';
  if (Math.abs(value) >= 100_000_000) return `${numberFormatter.format(value / 100_000_000)}亿`;
  if (Math.abs(value) >= 10_000) return `${numberFormatter.format(value / 10_000)}万`;
  return numberFormatter.format(value);
}

export function formatShanghaiTime(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}
