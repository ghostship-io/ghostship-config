import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repository = 'https://persistent.oaistatic.com/codex-app-prod/linux/deb';
export function parsePackageIndex(text) {
  const packages = text.trim().split(/\n\s*\n/).map((paragraph) => Object.fromEntries(
    paragraph.split('\n').filter((line) => /^[A-Za-z][A-Za-z0-9-]*: /.test(line)).map((line) => {
      const colon = line.indexOf(':');
      return [line.slice(0, colon), line.slice(colon + 1).trim()];
    }),
  )).filter((entry) => entry.Package === 'chatgpt' && entry.Architecture === 'arm64');
  if (packages.length !== 1) throw new Error('Expected exactly one stable ChatGPT ARM64 package');
  const entry = packages[0];
  if (!/^\d+(?:\.\d+){2,3}$/.test(entry.Version)) throw new Error('Unrecognized stable version format');
  if (entry.Filename !== `pool/main/c/chatgpt/chatgpt_${entry.Version}_arm64.deb`) throw new Error('Unexpected package path');
  if (!/^[a-f0-9]{64}$/.test(entry.SHA256)) throw new Error('Invalid package SHA256');
  return {
    desktopVersion: entry.Version, platform: 'linux-arm64',
    url: `${repository}/${entry.Filename}`, sha256: entry.SHA256,
    compatibilityFamily: 'contract-v1',
  };
}

export function verifyIndex(release, index) {
  const expiry = release.match(/^Valid-Until: (.+)$/m)?.[1];
  if (expiry && (!Number.isFinite(Date.parse(expiry)) || Date.parse(expiry) < Date.now())) {
    throw new Error('Repository metadata has expired');
  }
  const shaSection = release.match(/^SHA256:\n((?:[ \t].*\n?)+)/m)?.[1] || '';
  const expected = shaSection.split('\n').map((line) => line.trim().split(/\s+/))
    .find((fields) => fields[2] === 'main/binary-arm64/Packages');
  if (!expected || Number(expected[1]) !== index.length ||
      createHash('sha256').update(index).digest('hex') !== expected[0]) {
    throw new Error('Package index does not match signed metadata');
  }
}

export async function discoverRelease(keyring) {
  const work = await mkdtemp(path.join(tmpdir(), 'chatgpt-release-'));
  async function download(name) {
    const response = await fetch(`${repository}/dists/stable/${name}`, { signal: AbortSignal.timeout(60000) });
    if (!response.ok) throw new Error(`Repository request failed: ${response.status}`);
    const data = Buffer.from(await response.arrayBuffer());
    if (data.length > 16 * 1024 * 1024) throw new Error('Repository metadata is too large');
    return data;
  }
  try {
    const signed = path.join(work, 'InRelease');
    const verified = path.join(work, 'Release');
    await writeFile(signed, await download('InRelease'));
    const result = spawnSync('gpgv', ['--keyring', path.resolve(keyring), '--output', verified, signed], { encoding: 'utf8' });
    if (result.status !== 0) throw new Error(`OpenAI repository signature verification failed: ${result.stderr}`);
    const index = await download('main/binary-arm64/Packages');
    verifyIndex(await readFile(verified, 'utf8'), index);
    return parsePackageIndex(index.toString('utf8'));
  } finally { await rm(work, { recursive: true, force: true }); }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const keyring = process.argv[2] || fileURLToPath(new URL('../releases/chatgpt-archive-keyring.gpg', import.meta.url));
  console.log(JSON.stringify(await discoverRelease(keyring), null, 2));
}
