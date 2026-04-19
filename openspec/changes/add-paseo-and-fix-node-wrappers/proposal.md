## Why

This repo already manages the core agent CLIs through a shared wrapper-plus-maintenance flow on develop hosts, but Paseo is missing from that toolchain even though it is designed to orchestrate Codex, Claude Code, and OpenCode through one daemon. At the same time, the WSL FHS exposure for `npm` and `npx` is currently broken: `/usr/bin/npm` and `/usr/bin/npx` resolve as raw Node shims whose relative `../lib/cli.js` lookup fails, which makes those advertised compatibility paths unreliable.

## What Changes

- Add repo-managed `paseo` packaging for develop hosts through the same maintained user-local install path and wrapper pattern used for the other agent CLIs.
- Extend `ghostship-agent-maintenance` to install and refresh `@getpaseo/cli` automatically alongside the existing managed agent tooling.
- Add a supported WSL-only Paseo daemon startup path so the Windows desktop app can connect to the WSL-hosted daemon without manual shell startup after each reboot.
- Configure the managed Paseo daemon around the repo's WSL model: run as the `nixos` user, keep state under the user's home directory, and bind to a deliberate listen address suitable for Windows-to-WSL desktop access.
- Add explicit repo-managed `npm` and `npx` compatibility wrappers for WSL FHS paths instead of exposing the currently broken raw upstream shims directly at `/usr/bin`.
- Update active documentation and agent memory so the managed Paseo workflow, version/update expectations, activation steps, and `npm`/`npx` compatibility contract are documented accurately.

## Capabilities

### New Capabilities
- `develop-paseo-packaging`: define how develop hosts expose `paseo` through the managed wrapper and auto-update flow.
- `wsl-paseo-daemon-startup`: define the supported WSL systemd behavior for running a persistent Paseo daemon that the Windows desktop app can reach.
- `wsl-node-package-manager-fhs-wrappers`: define the supported WSL `/usr/bin/npm` and `/usr/bin/npx` compatibility path behavior.

### Modified Capabilities

## Impact

- Affected code: `modules/develop/agent-tooling.nix`, develop/WSL module wiring, any new systemd service definitions, and active docs under `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Affected systems: develop hosts, especially WSL develop hosts; no server-host behavior is intended to change.
- Dependencies/external behavior: depends on the upstream `@getpaseo/cli` package and the current Paseo daemon/client compatibility model, which should be documented because upstream currently expects daemon and app versions to stay in lockstep.
- Activation/manual implications: requires the relevant NixOS rebuild or switch before the managed `paseo` command, WSL daemon service, and `/usr/bin/npm` / `/usr/bin/npx` compatibility paths exist; the Windows desktop app will still need an initial manual connection to the WSL-hosted daemon.
