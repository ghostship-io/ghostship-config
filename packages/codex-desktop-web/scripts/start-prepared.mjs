import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = process.env.CODEX_DESKTOP_OUTPUT || path.join(packageRoot, "dist");
const executable = path.join(
  output,
  "runtime",
  process.platform === "win32" ? "electron.exe" : "electron",
);
const child = spawn(executable, ["--no-sandbox", "--disable-gpu"], {
  env: process.env,
  stdio: "inherit",
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exitCode = code ?? 1;
});
