import { afterEach, describe, expect, it, vi } from 'vitest';
import { readDashboard, readResults, type Result } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('static Trend Radar result reads', () => {
  it('preserves published attention priority even when a later stock has stronger contraction', async () => {
    const hot: Result = {
      symbol: '600000',
      name: '热门候选',
      heat_rank: 2,
      trend_days: 9,
      trend_start_date: '2026-09-01',
      trend_end_date: '2026-09-11',
      trend_return_pct: -9,
      trend_slope: -1,
      pullback_days: 2,
      max_pullback_pct: 2,
      trend_volume_avg: 90,
      baseline_volume_avg: 100,
      volume_ratio: 0.9,
      trend_amount_avg: 90,
      baseline_amount_avg: 100,
      amount_ratio: 0.9,
      is_strong_volume_contraction: false,
      highlight_level: 'normal',
    };
    const cold: Result = {
      ...hot,
      symbol: '600001',
      name: '其他候选',
      heat_rank: 0,
      volume_ratio: 0.2,
      is_strong_volume_contraction: true,
      highlight_level: 'strong',
    };
    const runId = '00000000-0000-0000-0000-000000000001';
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            schema_version: 1,
            run_id: runId,
            results: [hot, cold],
          }),
        ),
      ),
    );
    await expect(readResults(runId)).resolves.toEqual([hot, cold]);
  });
  it('accepts all-market rule parameters with a disabled rebound cap', async () => {
    const run = {
      id: '00000000-0000-0000-0000-000000000001',
      trade_date: '2026-09-11',
      status: 'success',
      trigger_type: 'cli',
      started_at: '2026-09-11T08:00:00Z',
      finished_at: '2026-09-11T09:00:00Z',
      payload: {
        data_as_of: '2026-09-11T09:00:00Z',
        heat_universe_count: 4800,
        candidate_count: 0,
        strong_contraction_count: 0,
        configuration_snapshot: {
          rule_version: 2,
          universe_scope: 'all_a',
          top_n: 300,
          min_days: 7,
          max_days: 9,
          max_pullback_days: 2,
          max_single_pullback_pct: null,
          baseline_volume_days: 20,
          strong_volume_ratio: 0.55,
        },
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            schema_version: 2,
            latest: run,
            attempts: [run],
          }),
        ),
      ),
    );
    await expect(readDashboard()).resolves.toEqual({ latest: run, attempts: [run] });
  });
  it('uses only a same-origin GET with no credentials and shows empty for initial 404', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('', { status: 404 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(readDashboard()).resolves.toEqual({ latest: null, attempts: [] });
    expect(fetcher).toHaveBeenCalledWith(
      '/data/trend-radar/index.json',
      expect.objectContaining({ method: 'GET', credentials: 'omit', cache: 'no-store' }),
    );
  });
  it('rejects a malformed or incompatible publication', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ schema_version: 3, latest: null, attempts: [] })),
        ),
    );
    await expect(readDashboard()).rejects.toThrow('invalid_result_index');
  });
  it('never fetches a path supplied as a run id', async () => {
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    await expect(readResults('../private')).rejects.toThrow('invalid_run_id');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('rejects result files belonging to another run', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ schema_version: 1, run_id: 'wrong', results: [] })),
        ),
    );
    await expect(readResults('00000000-0000-0000-0000-000000000001')).rejects.toThrow(
      'invalid_results',
    );
  });
  it('reports a network failure instead of inventing an empty successful dataset', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    await expect(readDashboard()).rejects.toThrow('result_read_failed');
  });
});
