import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { parsePackageIndex, verifyIndex } from '../scripts/discover-linux-release.mjs';

const index = Buffer.from(`Package: chatgpt
Version: 26.901.51231
Architecture: arm64
Filename: pool/main/c/chatgpt/chatgpt_26.901.51231_arm64.deb
SHA256: ${'a'.repeat(64)}
`);
const signed = `SHA256:\n ${createHash('sha256').update(index).digest('hex')} ${index.length} main/binary-arm64/Packages\n`;
test('Linux release is derived only from matching signed index bytes', () => {
  verifyIndex(signed, index);
  assert.equal(parsePackageIndex(index.toString()).desktopVersion, '26.901.51231');
  assert.throws(() => verifyIndex(signed, Buffer.from('tampered')), /signed metadata/);
  assert.throws(() => verifyIndex(`Valid-Until: Tue, 01 Jan 2000 00:00:00 UTC\n${signed}`, index), /expired/);
  assert.throws(() => parsePackageIndex(index.toString().replace('pool/main/', '../')), /package path/);
  assert.throws(() => parsePackageIndex(`${index}\n${index}`), /exactly one/);
});
