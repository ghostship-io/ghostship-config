## Why

The managed Agent Deck launcher name is more awkward than it needs to be, and
the current Ghostship OpenSpec workflow still splits planning across `main` and
apply-time worktree creation. Renaming the launcher and moving change-worktree
creation into propose will make the day-to-day workflow more consistent and
make the generated OpenSpec guidance match the way the repo is expected to be
used.

## What Changes

- Rename the managed develop-host launcher command from `agent-deck-launch` to
  `launch-agent`.
- Update the launcher contract and active docs so they describe `launch-agent`
  as the supported Agent Deck project-launch helper.
- Change the Ghostship `propose` override so it creates or reuses the change
  worktree before writing proposal, design, and tasks artifacts, and ends with a
  detailed overview of the full proposed change.
- Change the Ghostship `apply` override so it assumes the active change
  worktree already exists, keeps track of issues found during apply, and ends
  with a detailed overview of the completed work and any proposal updates made
  during apply.
- Change the Ghostship `archive` override so it ends with a list of issues or
  follow-up work that should be considered next.
- Refresh the active specs, docs, and changelog entries so they match the new
  launcher name and revised propose/apply/archive workflow.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `agent-deck-project-launcher`: Rename the required managed launcher command to
  `launch-agent` while keeping the same project-group and quick-title workflow.
- `ghostship-openspec-override-behavior`: Move worktree creation into propose,
  update apply to report completed work and proposal changes, and update archive
  to report next issues or follow-up work.

## Impact

- Affected systems: develop hosts and repo-local workflow files; no server-host
  runtime behavior changes are intended.
- Affected code: `home/profiles/develop.nix`,
  `modules/develop/agent-tooling.nix`, generated OpenSpec skill and command
  surfaces, and active docs/specs/changelog files.
- Manual implications: the renamed launcher will not exist until the relevant
  Home Manager or NixOS rebuild or switch is applied, and users will need to
  use `launch-agent` instead of `agent-deck-launch` after activation.
