## Why

`workmux` is no longer desired as a repo-managed develop-host tool and should be removed cleanly, including its live user-home artifacts. At the same time, `agent-deck` should stay, be bumped to the latest confirmed upstream release as of April 9, 2026 (`v1.4.1`), and gain a repo-managed background `agent-deck web` path for WSL develop hosts that is verified live, while the Ghostship OpenSpec override instructions gain tighter guardrails around proposal summaries, worktree editing, and apply-phase reuse.

## What Changes

- **BREAKING** Remove repo-managed `workmux` packaging and develop-profile exposure from the repo.
- Add explicit cleanup coverage for known `workmux` artifacts under `/home/nixos`, including related OpenCode integration files.
- Keep repo-managed `agent-deck`, bump it from `v1.3.4` to the latest confirmed upstream release `v1.4.1`, and define a supported background `agent-deck web` startup path for WSL develop hosts as a user service.
- Require live verification that the supported WSL `agent-deck web` user service starts successfully and that its web endpoint is reachable.
- Update the Ghostship OpenSpec override behavior so:
  - `propose` must end with a full proposed-plan summary for user review and tell agents to use Python-based file edits instead of `apply_patch` when working in a worktree.
  - `apply` must create or reuse the change worktree at the start, and if the user changes the work during apply, it must update the current proposal instead of creating a new proposal or a new worktree.
  - `archive` must attempt to leave `main` in a clean working state by reconciling or removing remaining related artifacts and reporting any leftovers that still require manual attention.
- Refresh active docs, specs, and changelog entries so they describe the new supported tooling and workflow rules accurately.

## Capabilities

### New Capabilities
- `ghostship-openspec-override-behavior`: Define the required Ghostship override behavior for propose, apply, and archive flows.
- `develop-agent-deck-web-startup`: Define the supported repo-managed background startup behavior for `agent-deck web` on WSL develop hosts.

### Modified Capabilities
- `develop-agent-deck-packaging`: Update the managed `agent-deck` package pin and document its continued support as a develop-profile tool.
- `develop-workmux-packaging`: Remove the requirement that `workmux` is packaged and exposed as a develop-profile tool, and define removal and cleanup expectations.

## Impact

- Affected code: local Nix packaging, overlay wiring, develop and WSL Home Manager wiring, OpenSpec wrapper override generation, and active docs/specs/changelog files.
- Affected systems: develop hosts, especially WSL develop hosts for the `agent-deck web` background-service behavior; no server-host service behavior changes are intended.
- Manual implications: known `/home/nixos` artifacts tied to `workmux` should be deleted as part of the change, while `agent-deck` state is expected to remain because the tool stays supported.
