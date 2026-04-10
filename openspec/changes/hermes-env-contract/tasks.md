## 1. Audit The Existing Hermes Env Surface

- [x] 1.1 Inventory the Hermes container `environment`, `environmentFiles`, and generated `runtime.env` inputs in `modules/self-hosted/hermes.nix`.
- [x] 1.2 Classify each current Hermes env variable as either a container-wide repo-managed input or an upstream-owned profile `.env` output.
- [x] 1.3 Identify every repo-managed path that still patches `~/.hermes/profiles/{assistant,operations,supervisor}/.env` directly.
- [x] 1.4 Record the audited container-wide static URL and topology inputs:
  unchanged pass-through vars such as `GOOGLE_AI_STUDIO_API_KEY`,
  `OPENROUTER_*`, `OPENAI_*`, `OPENCODE_*`, `BWS_*`, `BROWSERBASE_*`,
  `CAMOFOX_URL`, the utility service URLs and auth values, plus the translated
  source vars `DISCORD_GENERAL_CHANNEL_ID`, `DISCORD_*`, `WEBHOOK_*`, and
  `BROWSER_*_CDP_URL`.
- [x] 1.5 Record the audited generated runtime env inputs:
  current repo-projected utility auth values and note which of them now move to
  unchanged pass-through container env instead of a host-generated profile
  patching step.
- [x] 1.6 Record the direct `hermes-secrets` pass-through inputs that remain
  container-wide, including `GOOGLE_AI_STUDIO_API_KEY`,
  `OPENROUTER_API_KEY`, `OPENCODE_API_KEY`, `OPENCODE_GO_API_KEY`,
  `BWS_ACCESS_TOKEN`, and the per-profile Discord bot tokens.
- [x] 1.7 Confirm the current host-side profile patching scope: the repo writes
  upstream-owned profile translations and generated values today, so the
  cleanup must remove the full profile `.env` reconciliation path.

## 2. Move The Repo To The Container-Wide Contract

- [ ] 2.1 Update `modules/self-hosted/hermes.nix` so `hermes-profile-env-sync` only writes `/srv/apps/hermes/runtime.env` and no longer resolves profile IDs or patches `~/.hermes/profiles/{assistant,operations,supervisor}/.env`.
- [ ] 2.2 Keep the Hermes container env surface aligned to the upstream contract:
  unchanged pass-through inputs, `DISCORD_GENERAL_CHANNEL_ID`,
  `DISCORD_*`, `WEBHOOK_*`, `BROWSER_ASSISTANT_CDP_URL`,
  `BROWSER_OPERATIONS_CDP_URL`, `BROWSER_SUPERVISOR_CDP_URL`, and the
  explicit container-only runtime vars that upstream must exclude from profile
  `.env`.
- [ ] 2.3 Ensure the repo exposes the exact upstream browser/profile source vars
  `CLOAKBROWSER_URL`, `CLOAKBROWSER_TOKEN`, `BROWSER_ASSISTANT_CDP_URL`,
  `BROWSER_OPERATIONS_CDP_URL`, and `BROWSER_SUPERVISOR_CDP_URL` while
  removing repo-managed `BROWSER_CDP_URL` synthesis.
- [ ] 2.4 Remove or simplify `MANAGED_KEYS`, `resolve_profile_cdp_urls`, `patch_profile_env`, `patch_profiles`, and any path trigger that only existed to support host-side profile `.env` post-processing.

## 3. Validate The New Single-Writer Boundary

- [ ] 3.1 Build or evaluate the affected host config with a concrete verification command such as `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes.environmentFiles`.
- [ ] 3.2 Validate live on `chill-penguin` that the repo only supplies the
  upstream-supported source vars and does not write any final profile outputs
  such as `BROWSER_CDP_URL`, `DISCORD_BOT_TOKEN`, `WEBHOOK_SECRET`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_HOME_CHANNEL`, or `WEBHOOK_PORT`.
- [ ] 3.3 Validate live on `chill-penguin` that upstream `ghostship-hermes`
  writes `~/.hermes/profiles/{assistant,operations,supervisor}/.env` with the
  expected unchanged values, shared translations, per-profile translations,
  generated `WEBHOOK_ENABLED=true`, generated `WEBHOOK_PORT`, and
  `BROWSER_CDP_URL` from `BROWSER_*_CDP_URL`, without repo-managed patching.
- [ ] 3.4 Verify Hermes-side browser tooling against the managed assistant CloakBrowser profile by using the Hermes-bundled `ghostship-cloakbrowser` helper plus `agent-browser` on the live host.

## 4. Update Shared Documentation

- [ ] 4.1 Update `README.md` to describe the new Hermes env contract and the upstream ownership of managed profile `.env` files.
- [ ] 4.2 Update `CHANGELOG.md` with the Hermes env contract change.
- [ ] 4.3 Update `AGENTS.md` with the durable repo memory that the host owns container-wide Hermes env inputs while upstream owns managed profile `.env` rendering.
