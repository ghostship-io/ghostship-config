## Why

Hermes currently persists its native home directory under `/srv/apps/hermes/home`, but it does not expose a dedicated persistent workspace path for user-managed files. Adding a separate workspace mount now keeps long-lived Hermes data under `/srv/apps` without mixing that content into the image-managed home layout.

## What Changes

- Add a dedicated persistent host workspace at `/srv/apps/hermes/workspace` for Hermes.
- Bind-mount that host workspace directly into the Hermes container at `/home/hermes/workspace`.
- Extend the Hermes host tmpfiles setup so the workspace directory is created declaratively alongside `/srv/apps/hermes/home`.
- Update docs and repo memory to describe the split between Hermes home state and Hermes workspace state.
- Rebuild and switch `chill-penguin` so the live Hermes container picks up the new persistent workspace mount.

## Capabilities

### New Capabilities

### Modified Capabilities
- `hermes-native-layout`: Extend the Hermes layout contract so the container exposes a direct persistent workspace at `/home/hermes/workspace` backed by `/srv/apps/hermes/workspace`.

## Impact

- Affects server-host NixOS config only, especially [modules/self-hosted/hermes.nix](/home/nixos/nixos-config/.worktrees/hermes-workspace-mount/modules/self-hosted/hermes.nix).
- Requires documentation updates in [README.md](/home/nixos/nixos-config/.worktrees/hermes-workspace-mount/README.md), [CHANGELOG.md](/home/nixos/nixos-config/.worktrees/hermes-workspace-mount/CHANGELOG.md), and [AGENTS.md](/home/nixos/nixos-config/.worktrees/hermes-workspace-mount/AGENTS.md).
- Requires a `chill-penguin` activation so the live Hermes container is recreated with the new bind mount.
