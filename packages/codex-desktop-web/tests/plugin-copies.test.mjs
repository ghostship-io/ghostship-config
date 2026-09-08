import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';

const { installWritablePluginCopies } = createRequire(import.meta.url)('../bridge/writable-plugin-copies.cjs');

test('bundled plugin copies can be edited without changing sealed resources or symlink targets', async () => {
  const root = await fs.mkdtemp(path.join(tmpdir(), 'codex-plugin-copy-'));
  const source = path.join(root, 'resources/plugins/bundled');
  const destination = path.join(root, 'copy');
  const outside = path.join(root, 'outside');
  try {
    await fs.mkdir(source, { recursive: true });
    await fs.writeFile(path.join(source, 'plugin.json'), '{}', { mode: 0o444 });
    await fs.writeFile(outside, 'sealed', { mode: 0o444 });
    await fs.symlink(outside, path.join(source, 'link'));
    await fs.chmod(source, 0o555);
    const wrapped = { ...fs };
    installWritablePluginCopies(path.join(root, 'resources'), wrapped);
    await wrapped.cp(source, destination, { recursive: true, verbatimSymlinks: true });
    await fs.writeFile(path.join(destination, 'plugin.json'), '{"variant":"linux"}');
    assert.equal(await fs.readFile(path.join(source, 'plugin.json'), 'utf8'), '{}');
    assert.equal((await fs.stat(outside)).mode & 0o222, 0);
    assert.equal((await fs.stat(destination)).mode & 0o700, 0o700);
    await wrapped.cp(outside, path.join(root, 'ordinary-copy'));
    assert.equal((await fs.stat(path.join(root, 'ordinary-copy'))).mode & 0o222, 0);
  } finally {
    await fs.chmod(source, 0o755);
    await fs.rm(root, { recursive: true, force: true });
  }
});
