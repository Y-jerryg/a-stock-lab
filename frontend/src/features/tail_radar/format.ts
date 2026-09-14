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

const statusLabels: Record<string, string> = {
  pending: '待处理',
  running: '进行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  no_evidence: '无有效证据',
  claimed: '已领取任务',
  snapshot_running: '正在采集快照',
  screening_running: '正在筛选',
  candidate_analysis_running: '正在分析候选标的',
  partial_success: '部分完成',
};

const dataQualityLabels: Record<string, string> = {
  good: '良好',
  degraded: '部分降级',
  invalid: '无效',
  high: '高',
  medium: '中',
  low: '低',
  insufficient: '证据不足',
};

const pathLabels: Record<string, string> = {
  steady_strengthening: '稳步走强',
  late_acceleration: '尾盘加速',
  early_spike_followed_by_pullback: '早盘冲高后回落',
  recovery_from_intraday_weakness: '日内走弱后修复',
  materially_below_earlier_intraday_peak: '明显低于早前日内高点',
};

const claimLabels: Record<string, string> = {
  verified_fact: '已核实事实',
  interpretation: '分析解释',
  insufficient_evidence: '证据不足',
};

const publicationLabels: Record<string, string> = {
  verified: '发布时间已核实',
  uncertain: '发布时间不确定',
  unavailable: '无发布时间',
};

const availabilityLabels: Record<string, string> = {
  available_at_as_of: '截止时点前可获得',
  published_after_as_of: '截止时点后发布',
  uncertain_at_as_of: '截止时点可用性不确定',
};

const boardLabels: Record<string, string> = {
  shanghai_main: '沪市主板',
  shenzhen_main: '深市主板',
  chinext: '创业板',
  star: '科创板',
  beijing: '北交所',
};

export function formatStatus(value: string | null | undefined): string {
  if (!value) return '暂不可用';
  return statusLabels[value] ?? '未知状态';
}

export function formatDataQuality(value: string): string {
  return dataQualityLabels[value] ?? '未知';
}

export function formatPathLabel(value: string): string {
  return pathLabels[value] ?? '未定义的路径特征';
}

export function formatClaimClassification(value: string): string {
  return claimLabels[value] ?? '未分类';
}

export function formatPublicationStatus(value: string): string {
  return publicationLabels[value] ?? '发布时间状态未知';
}

export function formatSourceAvailability(value: string): string {
  return availabilityLabels[value] ?? '可用性未知';
}

export function formatBoard(value: string | null | undefined): string {
  if (!value) return '板块不可用';
  return boardLabels[value] ?? '未知板块';
}

export function formatIntradayPosition(value: number | null | undefined): string {
  return value == null ? '—' : `${formatNumber(value * 100, 0)}%`;
}
