## Context

This repo already has a stable pattern for develop-host agent tooling: lightweight Nix-managed wrapper commands delegate into a maintained user-local npm prefix, and `ghostship-agent-maintenance` owns automatic installation and refresh. Paseo belongs in that family because it orchestrates the same agent CLIs this repo already manages, but it introduces one extra concern that the current wrappers do not: a long-running daemon that external clients attach to.

The requested WSL behavior is also slightly unusual for this repo. Recent changes intentionally removed repo-managed background web services for other agent tooling on WSL, so adding Paseo should be justified as a daemon contract for desktop/mobile clients rather than a general return to "run every agent UI as a service". The service also has to respect Paseo's own security model and current version-compatibility guidance, which upstream documents as daemon/client lockstep.

Separately, the current WSL FHS compatibility layer exposes `/usr/bin/npm` and `/usr/bin/npx`, but those paths are broken because they point at raw upstream Node launcher shims whose relative `../lib/cli.js` lookup assumes the original npm installation layout. The repo needs an explicit compatibility contract there instead of silently depending on a path shape that does not work on this host.

## Goals / Non-Goals

**Goals:**
- Add `paseo` to the managed develop-host wrapper and auto-update flow.
- Define one supported WSL startup path for a persistent Paseo daemon that the Windows desktop app can attach to.
- Keep the WSL daemon state and runtime aligned with the existing `nixos` user and managed agent-tooling layout.
- Repair the supported `/usr/bin/npm` and `/usr/bin/npx` compatibility paths on WSL with explicit repo-managed wrappers.
- Document activation steps, version/update expectations, and the supported Windows-app connection model.

**Non-Goals:**
- Packaging the Paseo Electron desktop app itself inside this repo.
- Exposing Paseo on server-role hosts or outside the develop-host workflow.
- Opening the daemon broadly on all interfaces by default or defining a public remote-access contract.
- Reworking unrelated existing agent wrappers, skills, or OpenSpec workflow behavior.

## Decisions

### Decision: Package `paseo` through the existing managed npm-prefix wrapper flow
The repo should add a `paseo` wrapper through `mkInstalledAgentWrapper` and extend `ghostship-agent-maintenance` to install `@getpaseo/cli@latest` into `/home/nixos/.local/share/ghostship-agent-tools/npm`.

Why:
- It matches the user's request to use the same tooling as the other agent commands.
- It preserves one ownership model for agent CLIs instead of mixing declarative wrappers with ad-hoc local installs.
- The maintenance timer already exists and is the repo-approved place for automatic refresh behavior.

Alternatives considered:
- Pin Paseo as a Nix package in the flake: rejected because the current agent CLI model intentionally uses repo-managed wrappers over user-local upstream installs.
- Ask the user to install Paseo manually: rejected because it breaks the managed-tooling contract the user requested.

### Decision: Run Paseo as a WSL-only system service under the `nixos` user
The repo should define a WSL-only systemd service that executes `paseo start --foreground` as `User = "nixos"`, with `HOME=/home/nixos`, a stable `PASEO_HOME` under that home directory, and the same managed agent binary path available in the service environment.

Why:
- A system service survives login state and matches the user's explicit request for a systemd-managed daemon.
- Running as `nixos` keeps Paseo in the same credential and config context as the managed agent wrappers it will launch.
- `--foreground` lets systemd supervise the daemon directly instead of nesting another daemonization layer.

Alternatives considered:
- Home Manager user service: rejected because it depends more directly on user-session state and is less aligned with "always there for the Windows app" behavior.
- Launching Paseo only from an interactive shell wrapper: rejected because it does not satisfy the persistent-service requirement.

### Decision: Default the WSL daemon to localhost-only access and document desktop attachment
The managed service should default to a local listen address and host allowlist suitable for same-machine Windows attachment, with documentation describing Windows desktop connection to the WSL-hosted daemon and noting that broader remote access remains an explicit operator choice.

Why:
- Paseo upstream documents localhost binding as the safe default and warns about `0.0.0.0`.
- The user asked for Windows desktop attachment, not LAN exposure.
- Keeping the default local narrows accidental exposure while still supporting a documented same-machine workflow.

Alternatives considered:
- Bind to `0.0.0.0` by default: rejected because it widens the attack surface unnecessarily.
- Omit any repo-managed default and require the user to hand-write `~/.paseo/config.json`: rejected because the repo should define the supported service contract if it manages the service.

### Decision: Replace broken WSL `/usr/bin/npm` and `/usr/bin/npx` exposure with explicit wrappers
The repo should add explicit wrapper entrypoints for `npm` and `npx` that exec the real Nix store binaries, rather than relying on FHS-exposed raw launcher shims whose relative module lookups fail under `/usr/bin`.

Why:
- The current `/usr/bin/npm` and `/usr/bin/npx` behavior is demonstrably broken on this host.
- Explicit wrappers match the repo's existing WSL interop philosophy: support declared entrypoints, not accidental PATH or filesystem assumptions.
- This keeps the supported `/usr/bin/...` contract usable for Windows-side tools without changing the broader `envfs` model.

Alternatives considered:
- Drop `/usr/bin/npm` and `/usr/bin/npx` support entirely: rejected because the user explicitly asked to fix the wrappers and Windows-side tooling may rely on those FHS paths.
- Expose the raw npm shims through another filesystem path: rejected because the relative-lookup failure is inherent to the launcher layout, not the exact path name.

### Decision: Document Paseo version lockstep as part of the managed workflow
The change should explicitly document that upstream currently expects daemon and app versions to remain aligned, even though the repo will auto-update the CLI/daemon through maintenance.

Why:
- This is a real operational constraint from upstream documentation, not an implementation detail.
- Without documenting it, automatic updates could look "safe by default" when the Windows app may still need a matching update.

Alternatives considered:
- Ignore the compatibility note and treat Paseo like the other agent CLIs: rejected because it hides a known upstream constraint.

## Risks / Trade-offs

- [Upstream Paseo releases can move faster than the installed Windows app] → Mitigation: document the lockstep expectation clearly and keep the managed desktop-attachment workflow explicit in docs.
- [Windows-to-WSL localhost reachability could vary by host setup] → Mitigation: define one supported default listen contract, verify it in implementation, and document the exact connection target expected by the repo.
- [A persistent daemon service could be read as precedent for restoring other removed agent web services] → Mitigation: scope the spec narrowly around Paseo's daemon/client model and explicitly keep other removed web-service patterns out of scope.
- [Extra `/usr/bin` compatibility wrappers can drift from the underlying Node package layout] → Mitigation: make the wrappers thin exec shims to the Nix store binaries instead of mirroring npm's internal file tree.

## Migration Plan

1. Add the new OpenSpec deltas for managed Paseo packaging, WSL daemon startup, and WSL `npm`/`npx` wrapper behavior.
2. Implement the `paseo` wrapper and maintenance install step in the develop-host tooling layer.
3. Add the WSL-only systemd service and any supporting config or environment wiring needed for a supervised daemon.
4. Add explicit WSL `npm` and `npx` compatibility wrappers that invoke the real Nix store binaries.
5. Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the supported workflow and compatibility caveats.
6. Verify the target WSL host build and confirm the managed service and wrappers resolve correctly after activation.

Rollback would remove the Paseo wrapper and service wiring, drop the new compatibility wrappers, and revert the documentation/spec deltas.

## Open Questions

- Whether the final supported Windows desktop attachment target should be documented as `localhost:6767` specifically or as a repo-managed host/port value surfaced by the service implementation.
