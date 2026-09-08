"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");

function installWritablePluginCopies(resourcesPath, fileSystem = fs) {
  const sourceRoot = `${path.resolve(resourcesPath, "plugins")}${path.sep}`;
  const originalCopy = fileSystem.cp;
  async function makeWritable(target) {
    const stat = await fileSystem.lstat(target);
    if (stat.isSymbolicLink()) return;
    await fileSystem.chmod(target, stat.mode | (stat.isDirectory() ? 0o700 : 0o600));
    if (stat.isDirectory()) {
      for (const name of await fileSystem.readdir(target)) {
        await makeWritable(path.join(target, name));
      }
    }
  }
  fileSystem.cp = async function copy(source, destination, options) {
    const result = await originalCopy.call(this, source, destination, options);
    // Nix seals bundled resources read-only. Upstream copies their modes, then
    // edits plugin manifests and removes unsupported skills in the copy.
    if (typeof source === "string" && path.resolve(source).startsWith(sourceRoot)) {
      await makeWritable(destination);
    }
    return result;
  };
}

module.exports = { installWritablePluginCopies };
