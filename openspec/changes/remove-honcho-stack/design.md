## Context

Honcho is currently a fully managed self-hosted stack in this repo. It is imported through [modules/self-hosted/default.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/default.nix), exposed in Homepage, referenced by Hermes through `HONCHO_API_KEY` and `HONCHO_BASE_URL`, and still has active state on `chill-penguin` under `/srv/apps/honcho*` plus Hermes compatibility data under `/srv/apps/hermes/home/shared/honcho`.

The user wants Honcho removed entirely, not merely hidden from dashboards. That means the change has to cover service definitions, Hermes integration, dashboard visibility, secret references, host-retained state, and the associated repo documentation. It also intersects with the recently added `muximux-service-placement` capability because that spec still says Homepage keeps the Honcho tile.

## Goals / Non-Goals

**Goals:**
- Remove the managed Honcho runtime, including the app, Postgres, and Redis containers.
- Remove Hermes’ Honcho integration settings and any compatibility-state management tied to Honcho.
- Remove Honcho from Homepage and align the dashboard specs with the new no-Honcho state.
- Remove the Honcho-only `litellm-secrets` declaration and related secret material from the repo.
- Clean the retired Honcho state on `chill-penguin`, including `/srv/apps/honcho*` and Hermes’ retained Honcho compatibility files.

**Non-Goals:**
- Replace Honcho with another service in the same change.
- Redesign Hermes beyond removing its Honcho-specific integration.
- Preserve old Honcho state indefinitely for possible reuse after this retirement.
- Revisit unrelated dashboard placement or PriceBuddy behavior.

## Decisions

### Decision: Treat Honcho removal as full stack retirement, not a dashboard-only change

The source of truth for Honcho is the NixOS module import and the Hermes wiring, not the dashboard tiles. The implementation should remove [modules/self-hosted/honcho.nix](/home/nixos/nixos-config/.worktrees/remove-honcho-stack/modules/self-hosted/honcho.nix) from the self-hosted imports, stop generating the Honcho service definitions, and delete the remaining Homepage references.

Alternatives considered:
- Remove only the Homepage/Muximux tiles. Rejected because the runtime and Hermes dependency would still remain active on `chill-penguin`.
- Stop the live containers manually without removing the module. Rejected because the next activation would recreate them.

### Decision: Remove Hermes’ Honcho integration instead of keeping a dormant compatibility path

Hermes currently exports `HONCHO_API_KEY` and `HONCHO_BASE_URL` and preserves compatibility data under `shared/honcho`. If Honcho is no longer part of the supported stack, the repo should remove those env vars and the compatibility-state management rather than keeping a dead integration path that silently points nowhere.

Alternatives considered:
- Keep the Honcho env vars but point them to a disabled or nonexistent endpoint. Rejected because it preserves an unsupported integration and muddies troubleshooting.
- Keep the shared Honcho state forever for compatibility. Rejected because the user asked for clean host state and no longer needs the stack.

### Decision: Include explicit host-state retirement as part of the rollout

Removing the module is not enough: it stops future management, but it does not remove the persisted app, database, Redis, or Hermes compatibility files already on disk. The change should include an explicit host cleanup path that removes `/srv/apps/honcho`, `/srv/apps/honcho-db`, `/srv/apps/honcho-redis`, and the Hermes `shared/honcho` compatibility state once the stack is retired.

Alternatives considered:
- Leave the old directories on disk indefinitely. Rejected because the user explicitly wants clean host state.
- Rely on ad hoc manual shell cleanup with no repo tracking. Rejected because the cleanup is part of the durable behavior change and should be captured in the implementation and docs.

### Decision: Remove Honcho-only secrets as part of the same change

`litellm-secrets` is currently only referenced by Honcho, so retiring the stack should remove the secret declaration and the corresponding encrypted secret material rather than leaving dead secret inventory behind.

Alternatives considered:
- Leave the secret in place “just in case”. Rejected because it keeps stale secret surface area after the service is gone.

## Risks / Trade-offs

- [Hermes still expects Honcho internally] → Verify the live Hermes behavior after the env removal and treat any residual breakage as part of this retirement scope.
- [Host cleanup removes data someone later wants] → Call out the destructive cleanup explicitly in the proposal, tasks, and rollout notes before implementation.
- [Dashboard spec drift] → Update the existing `muximux-service-placement` capability in the same change so the new behavior is codified.
- [Secrets cleanup misses a remaining Honcho reference] → Search the repo and validate the host configuration after removing `litellm-secrets`.

## Migration Plan

1. Remove Honcho from the self-hosted imports and delete the Honcho module wiring.
2. Remove Hermes’ Honcho env vars and shared-state management.
3. Remove Honcho entries from Homepage and update docs/specs to reflect the retired stack.
4. Remove `litellm-secrets` from the repo-managed secrets configuration and encrypted secret inventory.
5. Deploy the updated system to `chill-penguin`.
6. Verify the Honcho services are no longer managed or running.
7. Clean the retired host state under `/srv/apps/honcho*` and Hermes’ retained `shared/honcho` data.

Rollback:
- Restore the Honcho module import and Hermes/Homepage wiring from Git and redeploy.
- Host-state cleanup is destructive, so rollback after cleanup would require restoring any needed data from backup or by reinitializing the service.

## Open Questions

- Whether Hermes needs a replacement memory or agent-integration path once Honcho is removed, or whether losing that capability is acceptable.
- Whether the host cleanup should delete Honcho state immediately on rollout or archive it elsewhere first.
