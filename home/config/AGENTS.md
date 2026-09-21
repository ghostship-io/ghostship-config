# Shared agent preferences

## Work

- Be concise. State material assumptions and blockers plainly.
- Scope changes to the request; preserve unrelated user work.
- Inspect the current environment instead of assuming NixOS, WSL, or a username.
- Keep project dependencies in the repo's Nix dev shell; run commands with
  `nix develop -c`. Use the existing container daemon and agent launchers.
- For Python, prefer `uv`, `ruff`, `pytest`, and `basedpyright` when the repo
  has no established alternatives.
- Use non-interactive commands. Keep credentials out of output and commits.
- Verify observable behavior with the smallest relevant checks.
- Update affected documentation, then commit verified work before handoff.
- For agent-facing documents, use `writing-for-agents`: keep common rules
  inline and put task-specific detail behind explicit references.

## Shared Ghostship tooling

- Store repo-local skills in `.agents/skills/<name>/SKILL.md`, installed shared
  skills in `~/.agents/skills`, and shared user instructions in
  `~/.agents/AGENTS.md`.
- Use `ghostship-agent-tooling` for managed installation and activation.
- Use `ghostship-bitwarden` for credentials and `ghostship-cloakbrowser` for
  browser profiles. Give each concurrent browser task its own profile.
- Use `ghostship-google-workspace` for Google services.
- Build API clients with Printing Press only. Search
  `ghostship-printing-press-library` and `generated/printing-press` before
  generating a new client through `ghostship-printing-press`. Keep
  `ghostship-*` wrappers as thin compatibility or workflow glue.

## WSL2 workers

- Prefer `/mnt/c/...` for Windows files. Treat `/mnt/share` as a lazy mount and
  verify it before use.
- Use repo-managed wrappers (`wsl-open`, `win-powershell`) or explicit
  `/mnt/c/...` paths when deterministic behavior matters; Windows PATH import
  is enabled but not authoritative.
- `powershell.exe -File` does not accept WSL `/mnt/c/...` paths, and a
  `\\wsl.localhost\...` working directory breaks drive-path commands. Pass a
  Windows path and `Set-Location 'C:\...'` when a drive path is required.
- FHS shim changes under `/bin` or `/usr/bin` can require a full WSL distro
  restart after a switch before the refreshed entries appear.
- This host runs T3 Code as a worker environment. Keep provider credentials and
  T3 Connect link state under the user home; they stay outside declarative
  configuration.
