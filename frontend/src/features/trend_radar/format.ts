import { locale, text } from '../../locales';

export function isMildRebound(maxPullbackPct: number) {
  return Number.isFinite(maxPullbackPct) && maxPullbackPct >= 0 && maxPullbackPct <= 2 + 1e-8;
}

export function marketTime(value: string | null | undefined) {
  if (!value) return text.trend.missing;
  return (
    new Intl.DateTimeFormat(locale, {
      timeZone: 'Asia/Shanghai',
      dateStyle: 'short',
      timeStyle: 'medium',
      hour12: false,
    }).format(new Date(value)) + text.trend.chinaTime
  );
}
export function percent(value: number | null, ratio = false) {
  return value == null || !Number.isFinite(value)
    ? text.trend.missing
    : `${(value * (ratio ? 100 : 1)).toFixed(1)}%`;
}
