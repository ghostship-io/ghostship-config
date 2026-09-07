import { createHash } from 'node:crypto';
import { chmod, copyFile, cp, mkdir, mkdtemp, readFile, rename, rm, symlink, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { createPackageWithOptions, extractAll } from '@electron/asar';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const values = { release: '26.901.51231', output: path.join(packageRoot, 'dist') };
for (let i = 2; i < process.argv.length; i++) {
  const name = process.argv[i];
  if (!['--release', '--release-file', '--archive', '--output'].includes(name)) throw new Error(`Unknown argument: ${name}`);
  values[name.slice(2)] = process.argv[++i];
}
if (!values.archive) throw new Error('--archive must name the verified official Linux .deb');
const release = JSON.parse(await readFile(values['release-file'] || path.join(packageRoot, 'releases', `${values.release}.json`), 'utf8'));
const archiveHash = createHash('sha256').update(await readFile(values.archive)).digest('hex');
if (archiveHash !== release.sha256) throw new Error('Official Linux package SHA256 mismatch');
const work = await mkdtemp(path.join(tmpdir(), 'chatgpt-linux-prepare-'));
const staged = `${path.resolve(values.output)}.staging-${process.pid}`;
function run(command, args) {
  const result = spawnSync(command, args, { stdio: 'inherit' });
  if (result.status !== 0) throw new Error(`${command} failed with exit ${result.status}`);
}
try {
  run('dpkg-deb', ['--extract', values.archive, path.join(work, 'deb')]);
  const source = path.join(work, 'deb/usr/lib/chatgpt');
  const extracted = path.join(work, 'app');
  extractAll(path.join(source, 'resources/app.asar'), extracted);
  const pkg = JSON.parse(await readFile(path.join(extracted, 'package.json'), 'utf8'));
  if (pkg.version !== release.desktopVersion || (release.electronVersion && pkg.devDependencies?.electron !== release.electronVersion)) {
    throw new Error('Linux application/runtime version does not match the release descriptor');
  }
  const preload = await readFile(path.join(extracted, '.vite/build/preload.js'), 'utf8');
  const channels = [...new Set(preload.match(/codex_desktop:[A-Za-z0-9:_-]+/g) || [])].sort();
  const contract = JSON.parse(await readFile(path.join(packageRoot, 'compatibility', `${release.compatibilityFamily}.json`), 'utf8'));
  for (const channel of contract.requiredPreloadChannels) {
    if (!channels.includes(channel)) throw new Error(`Missing required preload channel: ${channel}`);
  }
  const modules = [...preload.matchAll(/require\(["']([^"']+)["']\)/g)].map((match) => match[1]);
  if (modules.some((name) => name !== 'electron')) throw new Error(`Unsupported preload modules: ${modules.join(', ')}`);
  // Keep the Linux runtime, native modules, CLI, browser and bundled tools from
  // the same official package. Only our transport bootstrap is added to ASAR.
  await cp(source, path.join(staged, 'runtime'), { recursive: true });
  await cp(path.join(packageRoot, 'bridge'), path.join(extracted, 'bridge'), { recursive: true });
  const relayPreload = await readFile(path.join(extracted, 'bridge/combined-preload.cjs'), 'utf8');
  await writeFile(path.join(extracted, 'bridge/combined-preload.cjs'), `(() => {\n${preload}\n})();\n${relayPreload}`);
  await cp(path.join(packageRoot, 'node_modules/ws'), path.join(extracted, 'node_modules/ws'), { recursive: true });
  const browserAssets = path.join(extracted, 'bridge/browser');
  await writeFile(path.join(browserAssets, 'browser-preload.js'), `(() => {
const require = (name) => {
  if (name === 'electron') return window.__codexElectronModule;
  throw new Error('Unsupported preload module: ' + name);
};
const process = window.process;
${preload}
})();\n`);
  pkg.main = 'bridge/main-bootstrap.cjs';
  await writeFile(path.join(extracted, 'package.json'), `${JSON.stringify(pkg, null, 2)}\n`);
  const icon = path.join(source, 'resources/icon-chatgpt.png');
  for (const size of [180, 192, 512]) {
    run('convert', [icon, '-resize', `${size}x${size}`, path.join(browserAssets, `icon-${size}.png`)]);
  }
  for (const size of [192, 512]) {
    run('convert', [icon, '-resize', `${Math.floor(size * .8)}x${Math.floor(size * .8)}`, '-background', '#0d0d0d', '-gravity', 'center', '-extent', `${size}x${size}`, path.join(browserAssets, `icon-maskable-${size}.png`)]);
  }
  const resources = path.join(staged, 'runtime/resources');
  await createPackageWithOptions(extracted, path.join(resources, 'app.asar'), { unpack: '**/*.node' });
  await rename(path.join(resources, 'codex'), path.join(resources, 'codex-real'));
  await writeFile(path.join(resources, 'codex'), `#!/bin/sh
set -eu
if [ "\${1:-}" = app-server ] && [ -n "\${CODEX_CLI_PATH:-}" ]; then
  exec "$CODEX_CLI_PATH" "$@"
fi
exec "$(dirname "$0")/codex-real" "$@"
`);
  await chmod(path.join(resources, 'codex'), 0o755);
  await symlink('ChatGPT', path.join(staged, 'runtime/electron'));
  const manifest = {
    ...release, electronVersion: pkg.devDependencies?.electron, archiveSha256: archiveHash,
    preloadSha256: createHash('sha256').update(preload).digest('hex'),
    rendererIndexSha256: createHash('sha256').update(await readFile(path.join(extracted, 'webview/index.html'))).digest('hex'),
    preloadChannels: channels,
  };
  await writeFile(path.join(staged, 'release.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  await copyFile(path.join(staged, 'release.json'), path.join(resources, 'codex-web-compatibility.json'));
  await rm(values.output, { recursive: true, force: true });
  await rename(staged, values.output);
  console.log(`Prepared official ChatGPT Linux ${pkg.version}`);
} finally {
  await rm(work, { recursive: true, force: true });
  await rm(staged, { recursive: true, force: true });
}
