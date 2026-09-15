export type ScanStatus = 'running' | 'success' | 'completed_with_warnings' | 'failed';
export const hasResults = (status: ScanStatus) =>
  status === 'success' || status === 'completed_with_warnings';
export interface Run {
  id: string;
  trade_date: string | null;
  status: ScanStatus;
  started_at: string;
  finished_at: string | null;
  trigger_type: 'manual' | 'scheduled' | 'cli';
  payload: {
    data_as_of: string | null;
    heat_universe_count: number;
    candidate_count: number;
    strong_contraction_count: number;
    requested_count?: number;
    successful_count?: number;
    failed_count?: number;
    failed_symbols?: { symbol: string; name: string; error_code: string }[];
    configuration_snapshot: {
      rule_version?: 1 | 2;
      universe_scope?: 'top_heat' | 'all_a';
      top_n: number;
      min_days: number;
      max_days: number;
      max_pullback_days: number;
      max_single_pullback_pct: number | null;
      baseline_volume_days: number;
      strong_volume_ratio: number;
    };
  };
}
export interface Result {
  symbol: string;
  name: string;
  heat_rank: number;
  trend_days: number;
  trend_start_date: string;
  trend_end_date: string;
  trend_return_pct: number;
  trend_slope: number;
  pullback_days: number;
  max_pullback_pct: number;
  trend_volume_avg: number;
  baseline_volume_avg: number;
  volume_ratio: number;
  trend_amount_avg: number;
  baseline_amount_avg: number;
  amount_ratio: number | null;
  is_strong_volume_contraction: boolean;
  highlight_level: 'strong' | 'normal';
}

export interface DailyBar {
  symbol: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  adjustment_type: 'qfq';
  source: string;
  fetched_at: string;
}
export interface RunDetails {
  schema_version: 1;
  run: Run;
  volume_unit: 'lot';
  amount_unit: 'CNY';
  details: { candidate: Result; bars: DailyBar[] }[];
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const timestamp = (value: unknown) =>
  typeof value === 'string' && Number.isFinite(Date.parse(value));
function validRun(value: unknown): value is Run {
  if (!record(value) || !record(value.payload) || !record(value.payload.configuration_snapshot))
    return false;
  const payload = value.payload;
  const config = value.payload.configuration_snapshot;
  return (
    typeof value.id === 'string' &&
    uuid.test(value.id) &&
    ['running', 'success', 'completed_with_warnings', 'failed'].includes(String(value.status)) &&
    ['cli', 'scheduled', 'manual'].includes(String(value.trigger_type)) &&
    (value.trade_date === null ||
      (typeof value.trade_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.trade_date))) &&
    timestamp(value.started_at) &&
    (value.finished_at === null || timestamp(value.finished_at)) &&
    (payload.data_as_of === null || timestamp(payload.data_as_of)) &&
    ['heat_universe_count', 'candidate_count', 'strong_contraction_count'].every(
      (key) => finite(payload[key]) && payload[key] >= 0,
    ) &&
    ['requested_count', 'successful_count', 'failed_count'].every(
      (key) => payload[key] === undefined || (finite(payload[key]) && payload[key] >= 0),
    ) &&
    (payload.failed_symbols === undefined ||
      (Array.isArray(payload.failed_symbols) &&
        payload.failed_symbols.every(
          (row) =>
            record(row) &&
            typeof row.symbol === 'string' &&
            /^\d{6}$/.test(row.symbol) &&
            typeof row.name === 'string' &&
            typeof row.error_code === 'string',
        ))) &&
    [
      'top_n',
      'min_days',
      'max_days',
      'max_pullback_days',
      'baseline_volume_days',
      'strong_volume_ratio',
    ].every((key) => finite(config[key])) &&
    (config.rule_version === undefined || config.rule_version === 1 || config.rule_version === 2) &&
    (config.universe_scope === undefined ||
      config.universe_scope === 'top_heat' ||
      config.universe_scope === 'all_a') &&
    (config.max_single_pullback_pct === null || finite(config.max_single_pullback_pct))
  );
}
function validResult(value: unknown): value is Result {
  return (
    record(value) &&
    typeof value.symbol === 'string' &&
    /^\d{6}$/.test(value.symbol) &&
    typeof value.name === 'string' &&
    typeof value.trend_start_date === 'string' &&
    typeof value.trend_end_date === 'string' &&
    [
      'heat_rank',
      'trend_days',
      'trend_return_pct',
      'trend_slope',
      'pullback_days',
      'max_pullback_pct',
      'trend_volume_avg',
      'baseline_volume_avg',
      'volume_ratio',
      'trend_amount_avg',
      'baseline_amount_avg',
    ].every((key) => finite(value[key])) &&
    (value.amount_ratio === null || finite(value.amount_ratio)) &&
    typeof value.is_strong_volume_contraction === 'boolean' &&
    value.highlight_level === (value.is_strong_volume_contraction ? 'strong' : 'normal')
  );
}
async function readFile(relative: string, allowMissing = false): Promise<unknown> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/trend-radar/${relative}`, {
    method: 'GET',
    cache: 'no-store',
    credentials: 'omit',
    signal: AbortSignal.timeout(15000),
  });
  if (allowMissing && response.status === 404) return null;
  if (!response.ok) throw new Error('result_read_failed');
  const value: unknown = await response.json();
  return value;
}
export async function readDashboard(): Promise<{ latest: Run | null; attempts: Run[] }> {
  const value = await readFile('index.json', true);
  if (value === null) return { latest: null, attempts: [] };
  if (
    !record(value) ||
    (value.schema_version !== 1 && value.schema_version !== 2) ||
    !Array.isArray(value.attempts) ||
    !value.attempts.every(validRun) ||
    (value.latest !== null && !validRun(value.latest))
  ) {
    throw new Error('invalid_result_index');
  }
  const latest = value.latest;
  if (
    latest &&
    (!hasResults(latest.status) ||
      !value.attempts.some((run) => run.id === latest.id && hasResults(run.status)))
  ) {
    throw new Error('invalid_latest_result');
  }
  return { latest, attempts: value.attempts };
}
export async function readResults(runId: string): Promise<Result[]> {
  if (!uuid.test(runId)) throw new Error('invalid_run_id');
  const value = await readFile(`runs/${runId}.json`);
  if (
    !record(value) ||
    value.schema_version !== 1 ||
    value.run_id !== runId ||
    !Array.isArray(value.results) ||
    !value.results.every(validResult) ||
    new Set(value.results.map((row) => row.symbol)).size !== value.results.length
  ) {
    throw new Error('invalid_results');
  }
  // Publication has already applied the run's attention threshold and volume ordering.
  return value.results;
}

function validBars(value: unknown, symbol: string, run: Run): value is DailyBar[] {
  if (!Array.isArray(value) || !run.trade_date || !run.payload.data_as_of) return false;
  let previous = '';
  for (const bar of value) {
    if (
      !record(bar) ||
      bar.symbol !== symbol ||
      typeof bar.trade_date !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}$/.test(bar.trade_date) ||
      bar.trade_date <= previous ||
      bar.trade_date > run.trade_date ||
      bar.adjustment_type !== 'qfq' ||
      typeof bar.source !== 'string' ||
      !timestamp(bar.fetched_at) ||
      Date.parse(String(bar.fetched_at)) > Date.parse(run.payload.data_as_of) ||
      !['open', 'high', 'low', 'close'].every((key) => finite(bar[key]) && bar[key] > 0) ||
      !['volume', 'amount'].every((key) => finite(bar[key]) && bar[key] >= 0)
    )
      return false;
    if (
      Number(bar.low) > Math.min(Number(bar.open), Number(bar.close)) ||
      Number(bar.high) < Math.max(Number(bar.open), Number(bar.close))
    )
      return false;
    previous = bar.trade_date;
  }
  return true;
}

export async function readRunDetails(runId: string): Promise<RunDetails | null> {
  if (!uuid.test(runId)) throw new Error('invalid_run_id');
  const value = await readFile(`details/${runId}.json`, true);
  if (value === null) return null;
  if (
    !record(value) ||
    value.schema_version !== 1 ||
    !validRun(value.run) ||
    value.run.id !== runId ||
    !hasResults(value.run.status) ||
    value.volume_unit !== 'lot' ||
    value.amount_unit !== 'CNY' ||
    !Array.isArray(value.details)
  )
    throw new Error('invalid_run_details');
  const run = value.run;
  if (
    !value.details.every(
      (item) =>
        record(item) &&
        validResult(item.candidate) &&
        validBars(item.bars, item.candidate.symbol, run) &&
        (item.bars.length === 0 || item.bars.at(-1)?.trade_date === item.candidate.trend_end_date),
    )
  )
    throw new Error('invalid_run_details');
  const details = value.details as RunDetails['details'];
  if (
    details.length !== run.payload.candidate_count ||
    new Set(details.map((item) => item.candidate.symbol)).size !== details.length
  )
    throw new Error('invalid_run_details');
  return { schema_version: 1, run, volume_unit: 'lot', amount_unit: 'CNY', details };
}
