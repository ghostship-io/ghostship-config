# Project instructions

- Follow [shared preferences](home/config/AGENTS.md).
- Validate with `nix develop .#ci -c scripts/check`; stage new Nix files first.
  Use `nix develop .#browser` when local Playwright browsers are required.
- Work on a named branch in an isolated worktree. Commit verified changes,
  push, and open a draft PR. Resolve CI failures, merge conflicts, and review
  comments; mark ready when checks pass. Leave merging to the user.
- One feature thread owns a feature end to end and coordinates directly with
  the threads its work touches. Workers implement bounded briefs. Free workers
  run outside T3 Code on the separate `ghostship-worker` runtime and take only
  public-sensitivity work. The current routing policy in
  `ghostship-agent/config/agents/routing-policy.md` owns model choices, so do
  not pin models here.
- Bump `VERSION` and update `CHANGELOG.md` for completed changes.
- Cloudflare Access bypasses, direct Internet listeners and public IPv6 rules
  require explicit user approval recorded in the service configuration. Every
  Internet-facing service requires an enabled, attached AppArmor profile; use
  narrow executable, interpreter, file and library permissions. See
  [public-service policy](docs/plex-apparmor.md) before changing exposure.
- Prefer extremely strict AppArmor allowlists in complain mode while learning.
  Add permissions only for verified legitimate workloads; isolate interpreters
  with narrowly scoped resources. Enforce only after the documented learning gate.
- Deploy through committed Git changes and direct root SSH on the target host.
  Take the deploy slot on the host, build (with `--impure` where the build
  reads local firmware), dry-activate, then activate with
  `scripts/activate-host --holder`; `--verify-only --holder` releases it. An
  owner request to deploy or restart is carried out promptly.
  See [the deployment procedure](docs/agent-operations.md#remote-access-and-deployment).
  If push or SSH access fails, report the blocker. Do not call `sudo`.
- Every use of this repository must preserve the active T3 Code session. Do not
  stop, restart, recreate or auto-update `t3code` or its inner runtime, except
  when the owner has asked for that work to be deployed or activated. That
  owner request is the approval for the restart it needs and is recorded with
  `--owner-request`; keep the tool-maintenance and memory guards, bypass only the idle gate
  when the recorded request requires it, and
  follow the session guard in
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
