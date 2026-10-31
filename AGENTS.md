# Project instructions

- Follow [shared preferences](home/config/AGENTS.md).
- Run focused fast unit tests with `nix develop .#ci -c`; stage new Nix files first.
  Use `nix develop .#browser` when local Playwright browsers are required.
- Work on a named branch in an isolated worktree, against a frozen issue the
  PR names with `Refs #N`. Prove the exact head (`mvp check-proof` from a
  ghostship-agent checkout for a change without Go source) and submit it with
  `gsc review --repo ghostship-io/ghostship-config ISSUE PR HEAD PACKET SHA THREAD`.
  Review is the [review gate](https://github.com/ghostship-io/ghostship-agent/blob/epic/1105-mvp/docs/review-gate.md):
  the orchestrator is the primary reviewer and decides readiness, a specialist
  reviewer only when warranted, and the reviewed exact head is what lands.
- Keep `VERSION` and `CHANGELOG.md` out of PRs.
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
- T3 Code may restart after candidate acceptance passes for the exact image
  being activated. Deploys must verify that receipt before switching.

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
