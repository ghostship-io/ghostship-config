"use strict";

const nodeExecutable = process.env.T3CODE_NODE_EXECUTABLE;

if (
  nodeExecutable &&
  process.execPath.includes("/node_modules/@t3code/t3-")
) {
  Object.defineProperty(process, "execPath", {
    configurable: true,
    enumerable: true,
    writable: true,
    value: nodeExecutable,
  });
}
