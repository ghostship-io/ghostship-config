## Why

The live Hermes stack on `chill-penguin` currently has two writers for managed
profile `.env` files: the repo-hosted `hermes-profile-env-sync` logic and the
upstream `ghostship-hermes` bootstrap. That split contract causes clobbering,
which already surfaced as missing `BROWSER_CDP_URL` values even though the host
resolver and CloakBrowser profile inventory are healthy.

## What Changes

- Change the Hermes environment contract so the repo supplies only
  container-wide runtime inputs and upstream `ghostship-hermes` renders managed
  profile `.env` files.
- Stop repo-managed host logic from patching
  `~/.hermes/profiles/{assistant,operations,supervisor}/.env` directly.
- Keep the host responsible for generating the exact container runtime env
  inputs that upstream consumes, including unchanged shared provider and
  utility vars, per-profile source vars such as
  `BROWSER_ASSISTANT_CDP_URL` / `BROWSER_OPERATIONS_CDP_URL` /
  `BROWSER_SUPERVISOR_CDP_URL`, and the Discord/webhook source vars that
  upstream translates into each profile `.env`.
- Tighten the Hermes runtime docs and implementation plan around the new
  single-writer boundary.
- Call out the manual implication that upstream now writes generated profile
  outputs such as `BROWSER_CDP_URL`, `WEBHOOK_SECRET`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `DISCORD_HOME_CHANNEL`,
  `WEBHOOK_ENABLED=true`, and the profile-specific `WEBHOOK_PORT`.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `hermes-utility-runtime-env`: change the runtime env contract so the repo only
  projects container-wide Hermes inputs while upstream owns managed profile
  `.env` generation.

## Impact

- Affects the `chill-penguin` server-host Hermes module and its activation-time
  runtime env projection behavior.
- Affects the contract between repo-managed Nix config and the upstream
  `ghcr.io/ghostship-io/ghostship-hermes` container bootstrap.
- Requires follow-up coordination with upstream `ghostship-hermes` so the
  container populates managed profile `.env` values from the supplied
  container-wide environment using the exact per-profile translation contract.
