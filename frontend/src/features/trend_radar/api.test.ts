import { afterEach, describe, expect, it, vi } from 'vitest';
import { readDashboard, readResults } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('static Trend Radar result reads', () => {
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
