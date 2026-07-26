import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { decode, encode } = require(path.join(packageRoot, "bridge", "codec.cjs"));

test("bridge codec preserves binary payloads", () => {
  const source = {
    bytes: Uint8Array.from([0, 1, 127, 255]),
    nested: { value: "ok" },
  };
  const decoded = decode(encode(source));
  assert.deepEqual([...decoded.bytes], [0, 1, 127, 255]);
  assert.deepEqual(decoded.nested, { value: "ok" });
});
