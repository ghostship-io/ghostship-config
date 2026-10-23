# Project instructions

- Follow [shared preferences](home/config/AGENTS.md).
- Run focused fast unit tests with `nix develop .#ci -c`; stage new Nix files first.
  Use `nix develop .#browser` when local Playwright browsers are required.
- Work on a named branch in an isolated worktree. Workers implement and the
  orchestrator reviews each diff. Once approved with `agent review approve`,
  workers ship with `agent pr land` and deploy their own work.
- Keep `VERSION` and `CHANGELOG.md` out of PRs. `agent pr land` publishes one
  release commit on main; use a PR body `## Changelog` section for release
  notes and `Release: minor` or `Release: major` for an explicit larger bump.
- Cloudflare Access bypasses, direct Internet listeners and public IPv6 rules
  require explicit user approval recorded in the service configuration. Every
  Internet-facing service requires an enabled, attached AppArmor profile; use
  narrow executable, interpreter, file and library permissions. See
  [public-service policy](docs/plex-apparmor.md) before changing exposure.
- Prefer extremely strict AppArmor allowlists in complain mode while learning.
  Add permissions only for verified legitimate workloads; isolate interpreters
  with narrowly scoped resources. Enforce only after the documented learning gate.
- Deploy through committed Git changes and direct root SSH on the target host.
  If push or SSH access fails, report the blocker. Do not call `sudo`.
- Every use of this repository must preserve the active T3 Code session:
  do not force a busy restart. An owner request to deploy or activate permits
  its necessary restart; record that request through the guarded helper.
  Before activation, follow the session guard in
  [container workflow](docs/container-workflow.md#preserve-the-active-t3-code-session).

Read on demand:

- Internet-facing services or Plex AppArmor review: [public-service policy and learning workflow](docs/plex-apparmor.md).

- Agent instructions or skills: use the installed `writing-for-agents` skill.
- T3 Code setup, shared tools, skill discovery, or deployment from this
  container: [container workflow](docs/container-workflow.md).
- Windows/WSL2 worker environments: [WSL2 T3 Code workers](docs/wsl-t3-workers.md).
- Agent desktop (browsers, GUI automation, human access):
  [agent desktop](docs/agent-desktop.md). CDP detection testing:
  [cdp detection](docs/cdp-detection.md).
- NixOS/WSL, secrets, service activation, or host-specific pitfalls: the
  relevant section of [operating notes](docs/agent-operations.md).
- Boomer emulation or controller changes: [emulation guide](docs/boomer-kuwanger-emulation.md)
  and the Boomer notes in [operating notes](docs/agent-operations.md#nix-builds-and-host-boot).
  Deploy and verify on Boomer before declaring those changes complete.

Keep this file short. Put durable exceptions in the relevant reference; let
configuration and command help describe current tools, paths, and versions.
