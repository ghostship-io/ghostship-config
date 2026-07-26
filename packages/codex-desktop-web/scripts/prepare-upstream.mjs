import { createHash, createPublicKey, randomBytes, verify } from "node:crypto";
import { createWriteStream } from "node:fs";
import {
  chmod,
  copyFile,
  cp,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { get } from "node:https";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createPackageWithOptions, extractAll, listPackage } from "@electron/asar";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function parseArguments() {
  const values = {
    release: process.env.CODEX_DESKTOP_RELEASE || "26.721.41059",
    output: process.env.CODEX_DESKTOP_OUTPUT || path.join(packageRoot, "dist"),
    cache: process.env.CODEX_DESKTOP_CACHE || path.join(packageRoot, ".cache"),
  };
  for (let index = 2; index < process.argv.length; index += 1) {
    const argument = process.argv[index];
    if (argument === "--release") values.release = process.argv[++index];
    else if (argument === "--output") values.output = path.resolve(process.argv[++index]);
    else if (argument === "--cache") values.cache = path.resolve(process.argv[++index]);
    else throw new Error(`unknown argument: ${argument}`);
  }
  return values;
}

async function fileExists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

async function sha256(target) {
  const hash = createHash("sha256");
  hash.update(await readFile(target));
  return hash.digest("hex");
}

async function download(url, destination) {
  await mkdir(path.dirname(destination), { recursive: true });
  const partial = `${destination}.partial-${process.pid}`;
  await new Promise((resolve, reject) => {
    const request = get(url, (response) => {
      if (
        response.statusCode &&
        response.statusCode >= 300 &&
        response.statusCode < 400 &&
        response.headers.location
      ) {
        response.resume();
        download(response.headers.location, destination).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`download failed with HTTP ${response.statusCode}`));
        return;
      }
      const output = createWriteStream(partial, { mode: 0o600 });
      response.pipe(output);
      output.on("finish", () => output.close(resolve));
      output.on("error", reject);
    });
    request.on("error", reject);
  });
  await rename(partial, destination);
}

async function verifyReleaseArchive(archive, release) {
  const digest = await sha256(archive);
  if (digest !== release.sha256) {
    throw new Error(`archive SHA-256 mismatch: expected ${release.sha256}, got ${digest}`);
  }
  const rawKey = Buffer.from(release.ed25519PublicKey, "base64");
  const spkiKey = Buffer.concat([
    Buffer.from("302a300506032b6570032100", "hex"),
    rawKey,
  ]);
  const publicKey = createPublicKey({
    key: spkiKey,
    format: "der",
    type: "spki",
  });
  const valid = verify(
    null,
    await readFile(archive),
    publicKey,
    Buffer.from(release.ed25519Signature, "base64"),
  );
  if (!valid) throw new Error("archive Sparkle Ed25519 signature is invalid");
}

function run(command, arguments_, options = {}) {
  const result = spawnSync(command, arguments_, {
    encoding: "utf8",
    stdio: "inherit",
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(`${command} exited with status ${result.status}`);
  }
}

async function locateCodexBinary() {
  const openAiRoot = path.join(packageRoot, "node_modules", "@openai");
  const candidates = [];
  async function visit(directory, depth) {
    if (depth > 7 || !(await fileExists(directory))) return;
    const entries = await import("node:fs/promises").then(({ readdir }) =>
      readdir(directory, { withFileTypes: true }),
    );
    for (const entry of entries) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(target, depth + 1);
      else if (entry.name === "codex") candidates.push(target);
    }
  }
  await visit(openAiRoot, 0);
  for (const candidate of candidates) {
    const info = spawnSync(candidate, ["--version"], { encoding: "utf8" });
    if (info.status === 0 && info.stdout.includes("codex-cli")) return candidate;
  }
  throw new Error("could not locate the installed Linux Codex binary");
}

function extractPreloadChannels(source) {
  return [...new Set(source.match(/codex_desktop:[A-Za-z0-9:_-]+/g) || [])].sort();
}

async function replaceNativeModules(extractedRoot) {
  const betterSqliteRoot = path.join(packageRoot, "node_modules", "better-sqlite3");
  const upstreamBetterSqliteRoot = path.join(
    extractedRoot,
    "node_modules",
    "better-sqlite3",
  );
  await rm(upstreamBetterSqliteRoot, { force: true, recursive: true });
  await cp(betterSqliteRoot, upstreamBetterSqliteRoot, { recursive: true });

  const replacements = [
    {
      source: path.join(
        packageRoot,
        "node_modules",
        "node-pty",
        "build",
        "Release",
        "pty.node",
      ),
      destination: path.join(
        extractedRoot,
        "node_modules",
        "node-pty",
        "build",
        "Release",
        "pty.node",
      ),
    },
  ];
  for (const replacement of replacements) {
    if (!replacement.source || !(await fileExists(replacement.source))) {
      throw new Error(`missing rebuilt native module: ${replacement.source}`);
    }
    await mkdir(path.dirname(replacement.destination), { recursive: true });
    await copyFile(replacement.source, replacement.destination);
  }
  await cp(path.join(packageRoot, "node_modules", "ws"), path.join(extractedRoot, "node_modules", "ws"), {
    recursive: true,
  });
}

async function buildRelease(release, archive, output) {
  const workingRoot = await mkdtemp(path.join(tmpdir(), "codex-desktop-web-"));
  const extractedZip = path.join(workingRoot, "zip");
  const extractedAsar = path.join(workingRoot, "asar");
  const stagedOutput = `${output}.staging-${randomBytes(6).toString("hex")}`;
  const sourceResources = path.join(
    extractedZip,
    "ChatGPT.app",
    "Contents",
    "Resources",
  );
  await mkdir(extractedZip, { recursive: true });
  await mkdir(extractedAsar, { recursive: true });
  await mkdir(stagedOutput, { recursive: true });

  run("unzip", [
    "-q",
    "-o",
    archive,
    "ChatGPT.app/Contents/Resources/app.asar",
    "ChatGPT.app/Contents/Resources/app.asar.unpacked/*",
    "ChatGPT.app/Contents/Resources/plugins/*",
    "ChatGPT.app/Contents/Resources/skills/*",
    "ChatGPT.app/Contents/Resources/icon-chatgpt.png",
    "ChatGPT.app/Contents/Resources/codex-notification.wav",
    "-d",
    extractedZip,
  ]);

  extractAll(path.join(sourceResources, "app.asar"), extractedAsar);
  const upstreamPackagePath = path.join(extractedAsar, "package.json");
  const upstreamPackage = JSON.parse(await readFile(upstreamPackagePath, "utf8"));
  if (upstreamPackage.version !== release.desktopVersion) {
    throw new Error(
      `desktop version mismatch: expected ${release.desktopVersion}, got ${upstreamPackage.version}`,
    );
  }
  if (upstreamPackage.devDependencies?.electron !== release.electronVersion) {
    throw new Error(
      `Electron version mismatch: expected ${release.electronVersion}, got ${upstreamPackage.devDependencies?.electron}`,
    );
  }

  const upstreamPreloadPath = path.join(extractedAsar, ".vite", "build", "preload.js");
  const upstreamPreload = await readFile(upstreamPreloadPath, "utf8");
  const compatibility = JSON.parse(
    await readFile(
      path.join(packageRoot, "compatibility", `${release.compatibilityFamily}.json`),
      "utf8",
    ),
  );
  const channels = extractPreloadChannels(upstreamPreload);
  for (const channel of compatibility.requiredPreloadChannels) {
    if (!channels.includes(channel)) {
      throw new Error(`compatibility contract is missing required channel ${channel}`);
    }
  }

  await cp(path.join(packageRoot, "bridge"), path.join(extractedAsar, "bridge"), {
    recursive: true,
  });
  await copyFile(
    path.join(packageRoot, "bridge", "browser", "webview-bridge.js"),
    path.join(extractedAsar, "bridge", "browser", "webview-bridge.js"),
  );
  const generatedPreload = `(() => {
  const require = (specifier) => {
    if (specifier === "electron") return window.__codexElectronModule;
    throw new Error("[codex-web] unsupported preload module: " + specifier);
  };
  const process = window.process;
${upstreamPreload}
})();
`;
  await writeFile(
    path.join(extractedAsar, "bridge", "browser", "browser-preload.js"),
    generatedPreload,
  );

  upstreamPackage.main = "bridge/main-bootstrap.cjs";
  await writeFile(upstreamPackagePath, `${JSON.stringify(upstreamPackage, null, 2)}\n`);
  await replaceNativeModules(extractedAsar);

  const iconSource = path.join(sourceResources, "icon-chatgpt.png");
  const browserAssets = path.join(extractedAsar, "bridge", "browser");
  run("convert", [iconSource, "-resize", "180x180", path.join(browserAssets, "icon-180.png")]);
  run("convert", [iconSource, "-resize", "192x192", path.join(browserAssets, "icon-192.png")]);
  run("convert", [iconSource, "-resize", "512x512", path.join(browserAssets, "icon-512.png")]);
  run("convert", [
    iconSource,
    "-resize",
    "154x154",
    "-background",
    "#0d0d0d",
    "-gravity",
    "center",
    "-extent",
    "192x192",
    path.join(browserAssets, "icon-maskable-192.png"),
  ]);
  run("convert", [
    iconSource,
    "-resize",
    "410x410",
    "-background",
    "#0d0d0d",
    "-gravity",
    "center",
    "-extent",
    "512x512",
    path.join(browserAssets, "icon-maskable-512.png"),
  ]);

  const resourcesOutput = path.join(stagedOutput, "runtime", "resources");
  await cp(path.join(packageRoot, "node_modules", "electron", "dist"), path.join(stagedOutput, "runtime"), {
    recursive: true,
  });
  await mkdir(resourcesOutput, { recursive: true });
  await rm(path.join(resourcesOutput, "default_app.asar"), { force: true });
  await rm(path.join(resourcesOutput, "electron.asar"), { force: true });

  const appAsar = path.join(resourcesOutput, "app.asar");
  await createPackageWithOptions(extractedAsar, appAsar, {
    unpack: "**/*.node",
  });
  if (!listPackage(appAsar).includes("/bridge/browser/webview-bridge.js")) {
    throw new Error("prepared ASAR is missing the browser surface bridge");
  }

  for (const resourceName of ["plugins", "skills"]) {
    const source = path.join(sourceResources, resourceName);
    if (await fileExists(source)) {
      await cp(source, path.join(resourcesOutput, resourceName), { recursive: true });
    }
  }
  for (const resourceName of ["icon-chatgpt.png", "codex-notification.wav"]) {
    const source = path.join(sourceResources, resourceName);
    if (await fileExists(source)) {
      await copyFile(source, path.join(resourcesOutput, resourceName));
    }
  }

  const codexBinary = await locateCodexBinary();
  await copyFile(codexBinary, path.join(resourcesOutput, "codex-real"));
  await chmod(path.join(resourcesOutput, "codex-real"), 0o755);
  await writeFile(
    path.join(resourcesOutput, "codex"),
    `#!/bin/sh
set -eu
if [ -n "\${CODEX_CLI_PATH:-}" ]; then
  exec "$CODEX_CLI_PATH" "$@"
fi
exec "$(dirname "$0")/codex-real" "$@"
`,
  );
  await chmod(path.join(resourcesOutput, "codex"), 0o755);
  const ripgrep = spawnSync("sh", ["-c", "command -v rg"], { encoding: "utf8" });
  if (ripgrep.status === 0) {
    await copyFile(ripgrep.stdout.trim(), path.join(resourcesOutput, "rg"));
    await chmod(path.join(resourcesOutput, "rg"), 0o755);
  }

  const releaseManifest = {
    ...release,
    archiveSha256: await sha256(archive),
    preloadSha256: createHash("sha256").update(upstreamPreload).digest("hex"),
    rendererIndexSha256: createHash("sha256")
      .update(await readFile(path.join(extractedAsar, "webview", "index.html")))
      .digest("hex"),
    preloadChannels: channels,
    generatedAt: new Date().toISOString(),
  };
  await writeFile(
    path.join(resourcesOutput, "codex-web-compatibility.json"),
    `${JSON.stringify(releaseManifest, null, 2)}\n`,
  );
  await writeFile(
    path.join(stagedOutput, "release.json"),
    `${JSON.stringify(releaseManifest, null, 2)}\n`,
  );

  await rm(output, { recursive: true, force: true });
  await rename(stagedOutput, output);
  await rm(workingRoot, { recursive: true, force: true });
}

const arguments_ = parseArguments();
const releasePath = path.join(packageRoot, "releases", `${arguments_.release}.json`);
const release = JSON.parse(await readFile(releasePath, "utf8"));
const archive = path.join(arguments_.cache, path.basename(new URL(release.url).pathname));

if (!(await fileExists(archive)) || (await sha256(archive)) !== release.sha256) {
  await rm(archive, { force: true });
  console.log(`[prepare] downloading ChatGPT desktop ${release.desktopVersion}`);
  await download(release.url, archive);
}
console.log(`[prepare] verifying ${archive}`);
await verifyReleaseArchive(archive, release);
console.log(`[prepare] building compatibility family ${release.compatibilityFamily}`);
await buildRelease(release, archive, arguments_.output);
console.log(`[prepare] prepared ${arguments_.output}`);
