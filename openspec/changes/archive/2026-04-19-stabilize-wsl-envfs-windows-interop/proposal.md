## Why

WSL hosts in this repo intentionally enable `services.envfs` so Windows-side tools can rely on hardcoded FHS paths such as `/usr/bin/bash`. That works for Linux shell paths, but the current WSL setup also imports the Windows PATH into Linux PATH, which lets `envfs` synthesize Windows executables like `/usr/bin/powershell.exe`.

That mixed namespace is causing brittle behavior. `wsl-open` resolves `powershell.exe` through PATH, picks the synthetic `/usr/bin/powershell.exe` path, and fails on this host with `/usr/bin/powershell.exe: Invalid argument` even though the real Windows PowerShell path works. The repo needs a durable contract that keeps `envfs` for Linux/FHS compatibility while stopping accidental Windows `.exe` exposure through `/usr/bin`.

## What Changes

- Keep `services.envfs.enable = true` on WSL hosts for Linux/FHS compatibility such as `/usr/bin/bash`.
- Disable WSL's automatic Windows PATH import so `envfs` no longer synthesizes Windows executables from the imported host PATH.
- Keep Windows interop enabled, but expose supported Windows tools through explicit repo-managed entrypoints instead of depending on bare PATH lookup.
- Wrap `wsl-open` so it uses the real Windows PowerShell path instead of resolving `powershell.exe` from PATH.
- Update repo docs and WSL guidance to document the narrower, explicit Windows interop contract.

## Capabilities

### New Capabilities
- `wsl-envfs-windows-interop`: Define the supported WSL contract for keeping `envfs` Linux/FHS compatibility while using explicit Windows interop entrypoints instead of imported Windows PATH executables.

### Modified Capabilities
- None.

## Impact

- Affected systems: WSL develop hosts, Home Manager WSL profile, repo workflow docs, and WSL skill references.
- Affected code: `modules/wsl/default.nix`, `modules/wsl/wsl.nix`, `home/profiles/wsl.nix`, `README.md`, `AGENTS.md`, `CHANGELOG.md`, and `home/config/skills/wsl2/references/*.md`.
- Dependencies: continue to use `services.envfs`; rely on WSL interop without `appendWindowsPath`.
- Manual implications: bare `powershell.exe`, `cmd.exe`, `code`, and similar Windows commands will no longer be guaranteed through PATH on WSL hosts; supported Windows tools must use explicit wrappers or explicit `/mnt/c/...` paths.
