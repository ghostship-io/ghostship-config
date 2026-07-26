import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = process.env.CODEX_DESKTOP_OUTPUT || path.join(packageRoot, "dist");
const release = JSON.parse(await readFile(path.join(output, "release.json"), "utf8"));
const supported = JSON.parse(
  await readFile(path.join(packageRoot, "releases", "supported.json"), "utf8"),
);

if (!supported.supported.includes(release.desktopVersion)) {
  throw new Error(`${release.desktopVersion} is not registered as supported`);
}
if (!release.preloadChannels.includes("codex_desktop:message-from-view")) {
  throw new Error("preload contract is missing message-from-view");
}
if (!release.preloadChannels.includes("codex_desktop:connect-app-host")) {
  throw new Error("preload contract is missing transferred app-host port");
}

const manifestHash = createHash("sha256")
  .update(JSON.stringify(release.preloadChannels))
  .digest("hex");
console.log(
  JSON.stringify({
    desktopVersion: release.desktopVersion,
    compatibilityFamily: release.compatibilityFamily,
    preloadChannelCount: release.preloadChannels.length,
    preloadContractHash: manifestHash,
  }),
);
