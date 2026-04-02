## Why

Honcho is no longer needed in the Ghostship stack, but it still exists as a full runtime dependency: the service containers are running on `chill-penguin`, Hermes is configured to talk to it, Homepage still exposes it, and host state for Honcho remains on disk. Leaving it in place keeps unnecessary services, secrets, docs, and cleanup burden around even though the stack is no longer intended to use it.

## What Changes

- Remove the Honcho service stack from the self-hosted module imports and stop managing the Honcho app, database, and Redis containers.
- Remove Hermes' Honcho integration settings and any repo-managed compatibility logic that preserves or migrates Honcho state for Hermes.
- Remove Honcho entries from Homepage and related dashboard or documentation references so the repo no longer advertises Honcho as an active Ghostship service.
- Update the Muximux/Homepage placement contract so Honcho is absent from both dashboards rather than only hidden from Muximux.
- Include host cleanup guidance and implementation steps for retiring `/srv/apps/honcho*` state and stale Hermes Honcho compatibility data on `chill-penguin`.
- Remove the Honcho-only `litellm-secrets` declaration and any other repo-managed dependencies that become unused once the stack is retired.

## Capabilities

### New Capabilities
- `honcho-stack-retirement`: Defines the removal of the Honcho runtime, Hermes integration cleanup, and required host-state retirement steps on `chill-penguin`.

### Modified Capabilities
- `muximux-service-placement`: Change the dashboard requirement so Honcho is absent from Homepage as well as Muximux.

## Impact

- Affects server-host NixOS modules, especially [modules/self-hosted/default.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/default.nix), [modules/self-hosted/honcho.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/honcho.nix), [modules/self-hosted/hermes.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/hermes.nix), and [modules/self-hosted/homepage.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/homepage.nix).
- Requires host activation on `chill-penguin` and explicit cleanup of managed state under `/srv/apps/honcho*` and Hermes’ retained Honcho compatibility files.
- Requires removing the Honcho-only `litellm-secrets` declaration from the self-hosted secrets module and cleaning up any associated secret references that become unused.
- Requires documentation and repo-memory updates because this permanently changes the supported self-hosted service set and host-retirement workflow.
