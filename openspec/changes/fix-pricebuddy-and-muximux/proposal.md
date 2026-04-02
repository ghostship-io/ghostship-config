## Why

Muximux and Homepage have drifted away from the desired service layout on `chill-penguin`: Honcho still appears in the Muximux dropdown, and PriceBuddy is still hidden there instead of living on the main bar after Grimmory. PriceBuddy also has a deployment-specific reliability issue where the generated agent token file is being rewritten into an invalid repeated `id|token` format, and the current host investigation left unresolved whether any remaining failures are environment-driven or purely upstream application bugs.

## What Changes

- Remove Honcho from Muximux while leaving the existing Homepage Honcho entry intact.
- Move PriceBuddy out of the Muximux dropdown into the main bar and place it immediately after Grimmory.
- Update the generated Muximux configuration so the repo state matches the desired live `chill-penguin` layout instead of relying on ad hoc manual edits.
- Fix the PriceBuddy token-sync behavior so repeated service starts do not corrupt the persisted bearer token format.
- Add explicit runtime verification steps for PriceBuddy on `chill-penguin` to separate host-environment issues from known upstream application behavior such as Cloudflare-protected targets or app-side auth bugs.
- Document any required host activation and post-deploy verification steps in repo docs and change artifacts.

## Capabilities

### New Capabilities
- `muximux-service-placement`: Defines which Ghostship services appear on the Muximux main bar versus the dropdown, including stable ordering for promoted services.
- `pricebuddy-runtime-reliability`: Defines the generated PriceBuddy runtime artifacts and validation steps required for a working deployment on `chill-penguin`.

### Modified Capabilities

- None.

## Impact

- Affects server-host NixOS modules for `chill-penguin`, especially [modules/self-hosted/muximux.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/muximux.nix) and [modules/self-hosted/pricebuddy.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/pricebuddy.nix).
- Requires host activation on `chill-penguin` for repo-managed Muximux and PriceBuddy fixes to take effect.
- May require one-time manual cleanup or verification on `chill-penguin` if the live Muximux file is edited before the next rebuild or if a previously corrupted PriceBuddy agent token needs to be replaced.
- Requires follow-up documentation updates in `README.md`, `CHANGELOG.md`, and `AGENTS.md` if the implementation changes durable behavior or operator workflow.
