# Project instructions

- Follow [shared preferences](home/config/AGENTS.md).
- Validate with `nix develop .#ci -c scripts/check`; stage new Nix files first.
  Use `nix develop .#browser` when local Playwright browsers are required.
- Work on a named branch in an isolated worktree. Commit verified changes,
  push, and open a draft PR. Resolve CI failures, merge conflicts, and review
  comments; mark ready when checks pass. Leave merging to the user.
- Bump `VERSION` and update `CHANGELOG.md` for completed changes.
- Deploy through committed Git changes and direct root SSH on the target host.
  If push or SSH access fails, report the blocker. Do not call `sudo`.

Read on demand:

- Agent instructions or skills: use the installed `writing-for-agents` skill.
- T3 Code setup, shared tools, skill discovery, or deployment from this
  container: [container workflow](docs/container-workflow.md).
- NixOS/WSL, secrets, service activation, or host-specific pitfalls: the
  relevant section of [operating notes](docs/agent-operations.md).
- Boomer emulation or controller changes: [emulation guide](docs/boomer-kuwanger-emulation.md)
  and the Boomer notes in [operating notes](docs/agent-operations.md#nix-builds-and-host-boot).
  Deploy and verify on Boomer before declaring those changes complete.

Keep this file short. Put durable exceptions in the relevant reference; let
configuration and command help describe current tools, paths, and versions.
