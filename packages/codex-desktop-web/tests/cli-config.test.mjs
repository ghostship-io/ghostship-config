import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

test('desktop launch overrides preserve MCP transport and dotted feature keys', () => {
  const result = execFileSync('python3', [fileURLToPath(new URL('../bridge/cli-config.py', import.meta.url))], {
    input: JSON.stringify(['-c', 'features.code_mode_host=true', '--config',
      'mcp_servers.codex_app={command="/workstation/mcp",args=["server.mjs"],env={SOCKET="/tmp/app.sock"}}',
      '--config=features.code_mode_host=false', '-c', 'model=gpt-5',
      '-c', 'shell_environment_policy.inherit=all', '-c', 'use_legacy_landlock=true', 'app-server']),
    encoding: 'utf8',
  });
  assert.deepEqual(JSON.parse(result), {
    'features.code_mode_host': false,
    model: 'gpt-5',
    'shell_environment_policy.inherit': 'all',
    'features.use_legacy_landlock': true,
    'mcp_servers.codex_app': { command: '/workstation/mcp', args: ['server.mjs'], env: { SOCKET: '/tmp/app.sock' } },
  });
});
