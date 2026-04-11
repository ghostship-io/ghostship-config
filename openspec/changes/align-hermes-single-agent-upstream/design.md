## Context

The current `chill-penguin` Hermes host module still assumes the old repo-owned three-profile model: it seeds `assistant`/`operations`/`supervisor` assets, derives per-profile browser defaults from CloakBrowser, emits profile-scoped Discord inputs, and documents profile-facing `.env` files. Upstream `ghostship-hermes` has already collapsed to one managed runtime rooted at `/home/hermes/.hermes`, one generic env contract, one root seed layout, and a destructive bootstrap reset for legacy profile state.

This proposal intentionally follows the upstream break instead of preserving a local compatibility layer. The user also wants the cutover to reset Hermes persistence before deployment, and explicitly does not want the repo to provide a default `BROWSER_CDP_URL`. The latest upstream follow-up commits after the single-agent merge also tightened two details we should mirror in the host proposal: the managed root `.env` contract is now explicitly documented, and copied root skill seeds are normalized to writable runtime permissions. The one seed artifact that must survive the cutover is `skill-creator`. The single-agent runtime should reuse the current supervisor bot/auth identity, combine the current assistant, operations, and supervisor channels into the free-response Discord list, and keep the single-agent webhook on the first managed port (`8644`) with the current supervisor secret renamed into the generic secret contract. The root `SOUL.md` content will use the new Crush Crawfish single-agent prompt that combines personal assistance, operations, and software-delivery supervision in one profile.

## Goals / Non-Goals

**Goals:**
- Align the `chill-penguin` Hermes runtime contract with the upstream single-agent image model.
- Remove repo-managed profile-state assumptions from Nix modules, specs, and docs.
- Make the deployment plan explicitly destructive by resetting Hermes persistent state before the updated image boots.
- Keep `skill-creator` seeded through the upstream root seed layout.
- Leave Hermes with no repo-managed remote browser default so local `agent-browser` remains the upstream default behavior.
- Preserve the dedicated `Changedetection` CloakBrowser profile contract without keeping extra Hermes browser profiles alive.

**Non-Goals:**
- Preserve in-place migration of the old Hermes profile fleet or profile-local runtime state.
- Keep any profile-scoped env names, profile seed directories, or profile-specific browser defaults as compatibility aliases.
- Rework the shared `~/.agents/skills` model or the repo-wide shared-skill wiring outside the Hermes-specific seed paths.
- Redesign upstream `ghostship-hermes`; this change only realigns the host-side contract that feeds the image.

## Decisions

### 1. Treat the cutover as a destructive host-side reset

The deployment contract will remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before the updated Hermes container is started. The updated module will then recreate the host directories and let the image reseed its single-agent state and `/nix` contents from scratch.

Rationale:
- The user explicitly wants a full reset as part of the change.
- Upstream already treats the legacy profile tree as stale state to be removed, so a clean reset is simpler and lower-risk than inventing a one-off data migration.
- Resetting `/srv/apps/hermes/nix` avoids carrying forward stale managed-user installs or store state that was created against the old contract.

Alternatives considered:
- Migrate the existing profile tree in place. Rejected because it preserves complexity and leaves more room for hidden stale state.
- Reset only `/srv/apps/hermes/home`. Rejected because the old workspace and persisted `/nix` state would still encode the previous runtime contract and operator-installed tooling.

### 2. Adopt the upstream single-agent env contract without a browser default

Host wiring will stop producing profile-scoped Discord/webhook/browser source env and will instead supply only the generic single-agent inputs that upstream bootstrap expects. The module will not derive or export `BROWSER_CDP_URL`, `BROWSER_ASSISTANT_CDP_URL`, `BROWSER_OPERATIONS_CDP_URL`, or `BROWSER_SUPERVISOR_CDP_URL`.

Rationale:
- The user explicitly does not want a repo-managed `BROWSER_CDP_URL`.
- Upstream already defaults to local `agent-browser` when no remote browser CDP endpoint is provided.
- Removing CloakBrowser-derived defaults cleanly separates Hermes from the managed browser-profile inventory.

Alternatives considered:
- Map one existing CloakBrowser profile into generic `BROWSER_CDP_URL`. Rejected because it would reintroduce a Ghostship-specific browser-default layer the user does not want.
- Keep the old profile-specific browser vars and let upstream ignore them. Rejected because dead contract surface is still maintenance cost and operator confusion.

### 3. Collapse Hermes seeds to one root runtime-owned tree and keep `skill-creator`

The repo will replace `modules/self-hosted/hermes-seeds/profiles/...` with the upstream root seed layout under `/home/hermes/seeds/skills/<skill>/...` and `/home/hermes/seeds/SOUL.md`. `skill-creator` remains the one required repo-seeded Hermes skill and is copied only when the root runtime destination is missing. The copied runtime skill tree must also be normalized to writable Hermes-owned permissions so a read-only seed source does not leave the managed destination immutable. The root `SOUL.md` seed will use the new Crush Crawfish prompt that explicitly combines personal assistance, operations, and software-delivery supervision instead of reusing any existing profile persona unchanged.

Rationale:
- Upstream now seeds one root skill tree and one root `SOUL.md`, not profile-local copies.
- The user explicitly called out `skill-creator` as the seed content that must remain.
- Copy-if-missing behavior preserves operator ownership once the runtime has been initialized.

Alternatives considered:
- Keep category/profile-specific seed directories and generate a root view from them. Rejected because it keeps the old source model alive even after the runtime stops using it.
- Drop repo-managed Hermes seeding entirely. Rejected because the user still wants `skill-creator` seeded.

### 4. Preserve the upstream root `.env` details while omitting a browser default

The host-side proposal will mirror the current upstream managed `.env` details: `TERMINAL_CWD=/workspace`, `WEBHOOK_ENABLED=true`, and `WEBHOOK_PORT=8644` remain generated bootstrap defaults; `OPENCODE_GO_API_KEY` still backfills `OPENCODE_API_KEY` when needed; and fixed path/version selectors plus router-internal variables remain outside the managed `.env`. This repo still will not set `BROWSER_CDP_URL` itself, but it should keep the upstream optional-input contract intact for manual operator override later.

Rationale:
- Upstream documented these details immediately after the single-agent cutover, so they are now part of the active supported contract rather than incidental implementation behavior.
- Keeping the exclusions explicit prevents the repo from reintroducing router plumbing or fixed service selectors into the Hermes-facing env surface.
- This preserves optional manual remote-browser attachment without turning it into a Ghostship-managed default.

Alternatives considered:
- Leave these details implicit and only document the high-level single-agent env names. Rejected because upstream now treats the generated defaults and exclusions as an operator-facing contract.
- Remove `BROWSER_CDP_URL` from the supported contract entirely. Rejected because the user only asked not to set a default, not to break upstream manual override support.

### 5. Keep Discord and webhook policy generic and single-agent

The repo contract will move from three dedicated Hermes channels to one managed-agent Discord input set plus the existing mention-gating and no-auto-thread policy. Host wiring will feed generic env names and the specs will describe one configurable free-response channel list instead of three profile channels. The values behind that generic contract will use the current supervisor bot token and allowed-user scope, keep the current general channel as `DISCORD_HOME_CHANNEL`, and combine the current assistant, operations, and supervisor channel values into `DISCORD_FREE_RESPONSE_CHANNELS`.

Rationale:
- This matches the upstream env contract and avoids profile-specific translation logic.
- The user explicitly chose the current supervisor bot/auth scope as the surviving Discord identity while keeping all three existing role channels in the free-response list.
- The no-auto-thread behavior is still desired and still expressed in the upstream single-agent scaffold.
- The repo only needs one operator-facing Hermes agent after the cutover.

Alternatives considered:
- Preserve three free-response channels and multiplex them into one managed agent. Rejected because it keeps multi-profile routing semantics alive under a different name.
- Make every channel mention-only. Rejected because the existing routing policy intentionally preserves a free-response exception.

### 6. Use a new root `SOUL.md` while keeping the first managed webhook port

The root single-agent `SOUL.md` seed will use the provided Crush Crawfish prompt file. That persona stays direct, organized, and verification-focused while combining personal assistance, operations, and software-delivery supervision in one profile. The single-agent webhook contract will still use the first managed upstream port (`8644`), but the generic `WEBHOOK_SECRET` will reuse the current supervisor secret value under its renamed single-agent key.

Rationale:
- The user supplied a new root `SOUL.md` for the unified Crush Crawfish single-agent persona rather than reusing an existing profile prompt unchanged.
- Reusing the current supervisor secret reduces auth drift across the cutover while still conforming to the generic single-agent contract.
- Keeping `WEBHOOK_PORT=8644` matches the active upstream single-agent contract instead of carrying forward the old supervisor-specific port numbering.

Alternatives considered:
- Reuse an existing profile `SOUL.md` unchanged. Rejected because the user intends to replace it.
- Preserve the old supervisor webhook port. Rejected because upstream single-agent bootstrap now standardizes on the first managed webhook port.

### 7. Limit CloakBrowser defaults to `Changedetection`

`modules/self-hosted/cloakbrowser.nix` will stop seeding Hermes-facing managed browser profiles and will retain only the dedicated `Changedetection` default profile plus its keepalive behavior. Hermes will no longer depend on the CloakBrowser profile database for default browser configuration.

Rationale:
- The only remaining repo-managed browser-profile consumer after this change is changedetection.io.
- This removes an unnecessary cross-service coupling between Hermes startup and CloakBrowser profile inventory.
- It keeps the Changedetection behavior intact without undermining the no-default-browser-CDP decision.

Alternatives considered:
- Keep assistant/operations/supervisor profiles in CloakBrowser as inert extras. Rejected because dead defaults are still part of the operator contract.
- Remove the `Changedetection` profile too. Rejected because changedetection.io still relies on a dedicated persistent browser profile.

### 8. Update docs and repo memory in the same change

The implementation will update OpenSpec, `README.md`, `CHANGELOG.md`, and `AGENTS.md` together with the module changes so the repo stops describing the profile-fleet contract anywhere active.

Rationale:
- Current docs and repo memory strongly encode the profile model.
- A breaking runtime cutover without matching documentation would leave operators with invalid deployment and verification steps.

Alternatives considered:
- Land runtime changes first and rewrite docs later. Rejected because the deployment reset is too operationally significant to leave undocumented.

## Risks / Trade-offs

- [Risk] Resetting `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` discards operator state, local workspace content, and mutable runtime installs. → Mitigation: make the reset an explicit deployment step in tasks/docs and verify the new seed/rebuild behavior immediately after cutover.
- [Risk] Removing repo-managed browser defaults means remote-browser workflows will not work until an operator manually attaches one. → Mitigation: document that local `agent-browser` is the supported default and treat manual browser attachment as optional post-cutover setup.
- [Risk] Collapsing three Discord identities into one single-agent contract may still leave routing/auth expectations unclear. → Mitigation: keep the policy generic in specs, document that the single-agent runtime uses one supervisor-derived bot/auth scope, and explicitly combine the three existing role channels into `DISCORD_FREE_RESPONSE_CHANNELS`.
- [Risk] Root skill seeds may be copied from repo-managed read-only sources and remain unwritable in the managed runtime. → Mitigation: explicitly normalize copied seed permissions and verify writability in implementation validation.
- [Risk] Removing Hermes-facing CloakBrowser profiles could leave stale profile rows in existing CloakBrowser data. → Mitigation: because the Hermes side is being reset anyway, treat CloakBrowser default-profile cleanup as declarative convergence in the same change.

## Migration Plan

1. Update the Hermes host module, CloakBrowser bootstrap, Hermes seed assets, docs, and OpenSpec deltas in the change worktree so the repo describes only the single-agent contract.
2. Build or evaluate the changed `chill-penguin` configuration and verify the generated Hermes container env no longer includes profile-scoped browser or Discord inputs and does not emit `BROWSER_CDP_URL`.
3. On deployment, stop the Hermes container and remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before the updated service is started.
4. Start the updated Hermes service and let the image recreate `/home/hermes/.hermes`, reseed `/nix`, and bootstrap the root seed layout under `/home/hermes/seeds/`.
5. Verify the new runtime contract on the live host: no `~/.hermes/profiles` tree, root managed `.env` under `/home/hermes/.hermes/.env`, no default `BROWSER_CDP_URL`, and `skill-creator` copied from the root seed path into the managed skill tree.
6. Verify Changedetection still receives a dedicated CloakBrowser-backed CDP endpoint and its profile keepalive remains healthy.

Rollback strategy:
- Roll back by switching the repo to the previous revision and redeploying the older host configuration.
- Because the cutover deletes the previous Hermes state, rollback also requires reinitializing Hermes persistence from scratch or from an out-of-band backup rather than expecting an in-place state restore.

## Open Questions

- None currently.
