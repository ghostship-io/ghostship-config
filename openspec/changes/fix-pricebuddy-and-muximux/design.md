## Context

`chill-penguin` currently serves Muximux from a generated `settings.ini.php` file derived from [modules/self-hosted/muximux.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/muximux.nix). The live host has drifted from the desired layout: Grimmory is on the main bar, but both PriceBuddy and Honcho still appear in the dropdown. Homepage is already correct and should keep the Honcho entry.

PriceBuddy is deployed as three containers managed from [modules/self-hosted/pricebuddy.nix](/home/nixos/nixos-config/.worktrees/codex-fix-pricebuddy-and-muximux/modules/self-hosted/pricebuddy.nix): the app, MySQL, and the scraper sidecar. The host investigation found one concrete repo-side defect in the `pricebuddy-token-sync` logic: it reads back the already persisted `id|token` bearer value and reuses the entire string as the next raw token input, which causes repeated `id|` prefixes on subsequent starts. The same investigation also found app-side and external-site issues that should not be misdiagnosed as host environment failures.

This change touches multiple server-host modules and has live-host rollout implications, so it benefits from an explicit design before implementation.

## Goals / Non-Goals

**Goals:**
- Make the declarative Muximux configuration match the desired service layout on `chill-penguin`.
- Keep Homepage unchanged with Honcho still visible there.
- Ensure the generated PriceBuddy agent token file remains stable and valid across repeated restarts.
- Define runtime verification that distinguishes Ghostship deployment issues from upstream PriceBuddy or target-site behavior.
- Capture any required manual live-host cleanup as part of rollout rather than leaving it implicit.

**Non-Goals:**
- Redesign Muximux beyond the requested Honcho removal and PriceBuddy promotion.
- Fix upstream PriceBuddy application bugs such as the `Route [login] not defined` failure unless they are proven to be caused by Ghostship configuration.
- Bypass third-party anti-bot systems such as Cloudflare challenges encountered by specific PriceBuddy targets.
- Change Homepage layout or remove the existing Honcho Homepage entry.

## Decisions

### Decision: Keep Muximux placement declarative in the repo and treat direct host edits as temporary

Muximux layout is generated from the NixOS module, so the durable fix belongs in `modules/self-hosted/muximux.nix`, not only in `/srv/apps/muximux/www/muximux/settings.ini.php` on the host. The implementation should update the generated entry list so PriceBuddy is emitted directly after Grimmory with `dd=false`, and Honcho is no longer emitted into Muximux.

Alternatives considered:
- Edit the live `settings.ini.php` only. Rejected because the next activation would overwrite it.
- Leave Honcho present but disabled. Rejected because the request is to remove it from Muximux, not merely hide it ambiguously.

### Decision: Normalize the persisted PriceBuddy token before token-sync reuses it

`pricebuddy-token-sync` should treat the persisted file as an output artifact, not as the canonical raw secret. On each run it should extract the raw token portion before hashing and before rewriting `PRICEBUDDY_API_TOKEN="<id>|<raw-token>"`. That keeps the bearer format stable across restarts and avoids compounding prefixes.

Alternatives considered:
- Regenerate a brand-new random token on each start. Rejected because it would invalidate external clients and complicate deployments.
- Stop rewriting the token file after the initial bootstrap. Rejected because the token ID still needs to be recorded deterministically when the DB row is created or updated.

### Decision: Verify PriceBuddy with host-local service checks and classify residual failures explicitly

The implementation should verify PriceBuddy by checking generated env files, container health, scraper reachability from the app container, and the resulting token format after restart. Failures like Cloudflare challenge pages or the app’s `Route [login] not defined` error should be documented as residual upstream issues unless the new configuration changes them.

Alternatives considered:
- Treat any remaining PriceBuddy problem as a deployment failure. Rejected because the investigation already found app-side and target-side failures unrelated to Ghostship env wiring.
- Ignore residual errors once the token bug is fixed. Rejected because operators still need to know what is and is not fixed by this change.

## Risks / Trade-offs

- [Manual live edits diverge from repo state] → Update the Nix module and document that any emergency host-side Muximux edit is temporary until the next activation.
- [Token normalization misses an unexpected bearer format] → Parse conservatively, preserve the raw token suffix, and verify the rewritten file after a restart.
- [Residual PriceBuddy failures remain after env fixes] → Record them as known upstream or target-site issues during verification so the deployment is not treated as incomplete by default.
- [Removing Honcho from Muximux surprises users who relied on it there] → Keep the Homepage Honcho entry unchanged and call out the UI move in the changelog and rollout notes.

## Migration Plan

1. Update the repo-managed Muximux and PriceBuddy modules.
2. Rebuild and switch `chill-penguin` using the repo’s preferred deploy flow.
3. Verify the generated live Muximux file places PriceBuddy after Grimmory on the main bar and no longer includes Honcho.
4. Restart or redeploy PriceBuddy through the normal activation path and confirm `pricebuddy-agent.env` contains exactly one `<id>|<raw-token>` prefix pair.
5. Re-run container-level PriceBuddy checks and record any remaining upstream issues without conflating them with deployment regressions.

Rollback:
- Revert the module changes and redeploy the previous generation.
- If needed, restore the prior Muximux settings file from a regenerated older generation rather than maintaining an unmanaged fork on the host.

## Open Questions

- Whether implementation should remove the Honcho section entirely from generated Muximux config or leave a disabled stub for continuity. The current recommendation is complete removal.
- Whether the existing PriceBuddy auth-route error deserves a follow-up change after this deployment if it still reproduces under the corrected token/runtime setup.
