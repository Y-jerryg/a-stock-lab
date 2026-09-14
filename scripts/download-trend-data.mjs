// Used by Pages only. The token is never written into frontend files or logs.
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const repository = process.env.GITHUB_REPOSITORY;
const token = process.env.GH_TOKEN;
if (!repository || !/^[\w.-]+\/[\w.-]+$/.test(repository) || !token) {
  throw new Error('GitHub repository and CI token are required.');
}
const headers = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' };
const response = await fetch(`https://api.github.com/repos/${repository}/releases/tags/trend-radar-data`, {
  headers, signal: AbortSignal.timeout(30000),
});
if (response.status === 404 && process.env.REQUIRE_TREND_DATA !== 'true') {
  console.log('No published Trend Radar data yet; the website will show an empty state.');
} else {
  if (!response.ok) throw new Error(`Data release lookup failed (${response.status}).`);
  const release = await response.json();
  const asset = release.assets.find(item => item.name === 'trend-radar-public.zip');
  if (!asset) throw new Error('The data release exists but its public bundle is missing.');
  if (!Number.isSafeInteger(asset.id) || asset.size > 50 * 1024 * 1024) throw new Error('Invalid data asset.');
  const download = await fetch(`https://api.github.com/repos/${repository}/releases/assets/${asset.id}`, {
    headers: { ...headers, Accept: 'application/octet-stream' }, signal: AbortSignal.timeout(120000),
  });
  if (!download.ok) throw new Error(`Data download failed (${download.status}).`);
  const data = new Uint8Array(await download.arrayBuffer());
  if (data.length > 50 * 1024 * 1024) throw new Error('Data bundle exceeds size limit.');
  await mkdir(process.env.RUNNER_TEMP, { recursive: true });
  await writeFile(join(process.env.RUNNER_TEMP, 'trend-radar-public.zip'), data);
  console.log('Downloaded public results for validation.');
}
