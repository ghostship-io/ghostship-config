## Why

`workmux` fits the repo's develop-host workflow: it turns the existing
git-worktree plus `tmux` pattern into a single terminal-first tool for running
parallel agent tasks without branch switching or manual cleanup. Adding it as a
repo-managed develop utility keeps adoption declarative and consistent with the
current `agent-deck` and wrapper-based agent tooling instead of relying on
imperative upstream install commands.

## What Changes

- Add a repo-managed Nix package for the upstream `workmux` CLI.
- Expose `workmux` to users of the shared develop Home Manager profile as
  interactive tooling rather than a host-wide server baseline package.
- Standardize the initial repo-managed `workmux` path around the existing
  `tmux`-based workflow and document the required runtime assumptions.
- Document the managed `workmux` workflow, activation path, and any deliberate
  non-goals in active docs and changelog entries.

## Capabilities

### New Capabilities
- `develop-workmux-packaging`: Package and expose `workmux` as declarative
  develop-host tooling in this repo.

### Modified Capabilities

## Impact

- Affected code: develop-profile package wiring, local Nix packaging or flake
  input wiring, and related documentation.
- Affected systems: develop hosts using the shared Home Manager profile; no
  server-role host behavior changes are intended.
- Dependencies: upstream `workmux` release source plus the repo's existing
  `git` and `tmux` develop-host runtime baseline.
- Manual implications: users will need the relevant Home Manager or NixOS
  rebuild/switch before `workmux` becomes available in their shell, and any
  repo-local `.workmux.yaml` configuration remains out of scope unless added in
  a later change.
