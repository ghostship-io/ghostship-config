## Context

The current Hermes runtime on `chill-penguin` splits environment ownership
between repo-managed Nix code and upstream `ghostship-hermes` bootstrap logic.
The repo generates `/srv/apps/hermes/runtime.env` and then patches managed
profile `.env` files through `hermes-profile-env-sync`, while upstream
bootstrap also rewrites `~/.hermes/profiles/{assistant,operations,supervisor}/.env`.

That double-writer arrangement is fragile because both sides manage overlapping
keys. Live validation already showed the failure mode: the host-side sync ran
successfully and the assistant CloakBrowser profile existed, but the final
`~/.hermes/profiles/assistant/.env` still lacked `BROWSER_CDP_URL`. The better
contract is to let the repo provide container-wide runtime inputs and let
upstream own final per-profile `.env` assembly.

Current env audit:
- Upstream now defines four explicit profile-env behaviors:
  values copied unchanged into every managed profile `.env`, values translated
  into every profile `.env`, values translated per profile, and values
  generated into profile `.env` at bootstrap time.
- The unchanged pass-through set includes shared provider env, browser-provider
  env, and utility env such as `GOOGLE_AI_STUDIO_API_KEY`,
  `OPENROUTER_*`, `OPENAI_*`, `OPENCODE_*`, `GITHUB_TOKEN`, `GH_TOKEN`,
  `HASS_*`, `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BROWSERBASE_*`,
  `BROWSER_USE_API_KEY`, `CAMOFOX_URL`, `SEARXNG_URL`, `SONARR_*`,
  `RADARR_*`, `PROWLARR_*`, `PLEX_*`, `ROMM_*`, `NZBGET_*`,
  `QBITTORRENT_*`, `GRIMMORY_*`, `TAUTULLI_*`, `BAZARR_*`,
  `SYNOLOGY_*`, `FLARESOLVERR_URL`, `PYLOAD_*`, `CLOAKBROWSER_*`,
  `PRICEBUDDY_*`, `RSS_BRIDGE_URL`, `CHANGEDETECTION_*`, `CHAPTARR_*`,
  and `N8N_*`.
- The translated shared input is `DISCORD_GENERAL_CHANNEL_ID`, which upstream
  writes into every profile `.env` as `DISCORD_HOME_CHANNEL`.
- The translated per-profile inputs are:
  `DISCORD_ASSISTANT_*`, `WEBHOOK_ASSISTANT_SECRET`, and
  `BROWSER_ASSISTANT_CDP_URL` for `assistant`;
  `DISCORD_OPERATIONS_*`, `WEBHOOK_OPERATIONS_SECRET`, and
  `BROWSER_OPERATIONS_CDP_URL` for `operations`;
  `DISCORD_SUPERVISOR_*`, `WEBHOOK_SUPERVISOR_SECRET`, and
  `BROWSER_SUPERVISOR_CDP_URL` for `supervisor`.
- The generated upstream profile outputs are
  `TERMINAL_CWD=/workspace`, `WEBHOOK_ENABLED=true`, and per-profile
  `WEBHOOK_PORT` values `8644`, `8645`, and `8646`.
- Upstream also performs the compatibility normalization
  `OPENCODE_API_KEY <- OPENCODE_GO_API_KEY` when the former is unset.
- The explicit container-only exclusions are `HOME`, `HERMES_HOME`,
  `SSL_CERT_FILE`, `NIX_SSL_CERT_FILE`, `GHOSTSHIP_TERMINAL_CWD`,
  `GHOSTSHIP_HERMES_PROJECT_ROOT`, `GHOSTSHIP_HERMES_RUNTIME_FLAKE_REF`,
  `GHOSTSHIP_HERMES_PROFILES`, `GHOSTSHIP_HERMES_DEFAULT_PROFILE`,
  `GHOSTSHIP_HERMES_MANAGED_PROFILE`,
  `GHOSTSHIP_HERMES_SHARED_SKILLS_DIR`,
  `GHOSTSHIP_HERMES_PROFILE_SKILLS_ROOT`, `GHOSTSHIP_TOOLING_MODE`,
  `GHOSTSHIP_DASHBOARD_HOST`, every `GHOSTSHIP_ROUTER_*`,
  every `API_SERVER_*`, and the test-only
  `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_ID` /
  `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_SECRET`.
- Host-side profile patching currently duplicates much of that upstream-owned
  translation/rendering behavior, which is the contract we are removing.

## Goals / Non-Goals

**Goals:**
- Make the host/runtime contract single-writer for managed profile `.env`
  files.
- Keep repo-managed wiring responsible for projecting container-wide Hermes
  inputs such as utility URLs, selected utility secrets, and stable
  CloakBrowser manager connection details.
- Require upstream `ghostship-hermes` bootstrap to render profile-specific
  `.env` files, including `BROWSER_CDP_URL`, from those container-wide inputs.
- Remove the ambiguity about which layer owns `assistant`, `operations`, and
  `supervisor` profile env state.

**Non-Goals:**
- Redesign Hermes profile names, gateway units, or seed layout.
- Change CloakBrowser’s managed profile inventory or changedetection-specific
  launch contract.
- Define the exact upstream implementation beyond the contract it must satisfy.

## Decisions

### Make the repo own only container-wide runtime env

The repo will keep generating a single container-consumed runtime env surface
such as `/srv/apps/hermes/runtime.env` and related `environment` /
`environmentFiles` entries in the Hermes container definition. That surface is
the host-owned input contract.

This is preferred over patching profile `.env` files from the host because the
container runtime can consume one stable input surface without coordinating file
ownership across the container boundary.

Alternative considered: keep host-side profile patching and require upstream to
preserve unknown keys. Rejected because it still leaves two writers touching the
same files and depends on ordering and preservation semantics staying aligned.

Concrete contract after this change:
- Repo-owned unchanged pass-through inputs include
  `GOOGLE_AI_STUDIO_API_KEY`, `OPENROUTER_API_KEY`,
  `OPENROUTER_BASE_URL`, `OPENROUTER_HTTP_REFERER`,
  `OPENROUTER_TITLE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
  `OPENCODE_API_KEY`, `OPENCODE_GO_API_KEY`, `OPENCODE_BASE_URL`,
  `GITHUB_TOKEN`, `GH_TOKEN`, `HASS_URL`, `HASS_TOKEN`,
  `BWS_ACCESS_TOKEN`, `BWS_SERVER_URL`, `BROWSERBASE_API_KEY`,
  `BROWSERBASE_PROJECT_ID`, `BROWSER_USE_API_KEY`,
  `BROWSERBASE_PROXIES`, `BROWSERBASE_ADVANCED_STEALTH`,
  `BROWSERBASE_KEEP_ALIVE`, `BROWSERBASE_SESSION_TIMEOUT`,
  `BROWSER_INACTIVITY_TIMEOUT`, `CAMOFOX_URL`, `SEARXNG_URL`,
  `SONARR_URL`, `SONARR_API_KEY`, `RADARR_URL`, `RADARR_API_KEY`,
  `PROWLARR_URL`, `PROWLARR_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`,
  `ROMM_URL`, `ROMM_TOKEN`, `ROMM_USERNAME`, `ROMM_PASSWORD`,
  `NZBGET_URL`, `NZBGET_USER`, `NZBGET_PASS`, `QBITTORRENT_URL`,
  `QBITTORRENT_USER`, `QBITTORRENT_PASS`, `GRIMMORY_URL`,
  `GRIMMORY_TOKEN`, `GRIMMORY_USERNAME`, `GRIMMORY_PASSWORD`,
  `TAUTULLI_URL`, `TAUTULLI_API_KEY`, `BAZARR_URL`, `BAZARR_API_KEY`,
  `SYNOLOGY_URL`, `SYNOLOGY_USER`, `SYNOLOGY_PASS`,
  `SYNOLOGY_VERIFY_SSL`, `FLARESOLVERR_URL`, `PYLOAD_URL`,
  `PYLOAD_USER`, `PYLOAD_PASS`, `CLOAKBROWSER_URL`,
  `CLOAKBROWSER_TOKEN`, `PRICEBUDDY_URL`, `PRICEBUDDY_TOKEN`,
  `RSS_BRIDGE_URL`, `CHANGEDETECTION_URL`, `CHANGEDETECTION_API_KEY`,
  `CHAPTARR_URL`, `CHAPTARR_API_KEY`, `CHAPTARR_API_PATH`,
  `CHAPTARR_API_VERSION`, `N8N_URL`, `N8N_API_KEY`,
  `N8N_PUBLIC_API_ENDPOINT`, and `N8N_PUBLIC_API_VERSION`.
- Repo-owned translated source inputs are
  `DISCORD_GENERAL_CHANNEL_ID`,
  `DISCORD_ASSISTANT_BOT_TOKEN`,
  `DISCORD_ASSISTANT_ALLOWED_USERS`,
  `DISCORD_ASSISTANT_CHANNEL_ID`,
  `WEBHOOK_ASSISTANT_SECRET`,
  `BROWSER_ASSISTANT_CDP_URL`,
  `DISCORD_OPERATIONS_BOT_TOKEN`,
  `DISCORD_OPERATIONS_ALLOWED_USERS`,
  `DISCORD_OPERATIONS_CHANNEL_ID`,
  `WEBHOOK_OPERATIONS_SECRET`,
  `BROWSER_OPERATIONS_CDP_URL`,
  `DISCORD_SUPERVISOR_BOT_TOKEN`,
  `DISCORD_SUPERVISOR_ALLOWED_USERS`,
  `DISCORD_SUPERVISOR_CHANNEL_ID`,
  `WEBHOOK_SUPERVISOR_SECRET`, and
  `BROWSER_SUPERVISOR_CDP_URL`.
- Repo-owned container-only inputs remain available to the runtime but SHALL
  not be written into profile `.env`, including `HOME`, `HERMES_HOME`,
  `SSL_CERT_FILE`, `NIX_SSL_CERT_FILE`, `GHOSTSHIP_TERMINAL_CWD`,
  `GHOSTSHIP_HERMES_PROJECT_ROOT`, `GHOSTSHIP_HERMES_RUNTIME_FLAKE_REF`,
  `GHOSTSHIP_HERMES_PROFILES`, `GHOSTSHIP_HERMES_DEFAULT_PROFILE`,
  `GHOSTSHIP_HERMES_MANAGED_PROFILE`,
  `GHOSTSHIP_HERMES_SHARED_SKILLS_DIR`,
  `GHOSTSHIP_HERMES_PROFILE_SKILLS_ROOT`, `GHOSTSHIP_TOOLING_MODE`,
  `GHOSTSHIP_DASHBOARD_HOST`, every `GHOSTSHIP_ROUTER_*`,
  every `API_SERVER_*`, and the test-only
  `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_ID` /
  `GHOSTSHIP_TEST_CF_ACCESS_CLIENT_SECRET`.

### Make upstream own managed profile `.env` rendering

Upstream `ghostship-hermes` bootstrap and profile startup flows will become the
only writers of `~/.hermes/profiles/<profile>/.env`. They must read the
container-wide inputs and derive profile-specific values, including
`BROWSER_CDP_URL`, for `assistant`, `operations`, and `supervisor`.

This keeps profile lifecycle and profile env assembly in the same project,
which is where the profile semantics already live.

Alternative considered: move all `.env` rendering to the repo and stop upstream
from touching those files. Rejected because upstream already creates and
rewrites profile state and would need an additional compatibility contract just
to avoid undoing host-managed state.

Concrete upstream-owned profile outputs after this change:
- Profile `.env` rendering for `assistant`, `operations`, and `supervisor`.
- Shared profile outputs derived by translation or generation:
  `DISCORD_HOME_CHANNEL`, `TERMINAL_CWD=/workspace`,
  `WEBHOOK_ENABLED=true`, and compatibility `OPENCODE_API_KEY`
  normalization from `OPENCODE_GO_API_KEY` when needed.
- Assistant-only outputs:
  `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `WEBHOOK_SECRET`,
  `BROWSER_CDP_URL`, and `WEBHOOK_PORT=8644`.
- Operations-only outputs:
  `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `WEBHOOK_SECRET`,
  `BROWSER_CDP_URL`, and `WEBHOOK_PORT=8645`.
- Supervisor-only outputs:
  `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USERS`,
  `DISCORD_FREE_RESPONSE_CHANNELS`, `WEBHOOK_SECRET`,
  `BROWSER_CDP_URL`, and `WEBHOOK_PORT=8646`.

### Keep per-profile translation logic upstream

The repo should expose the per-profile source vars
`BROWSER_ASSISTANT_CDP_URL`, `BROWSER_OPERATIONS_CDP_URL`, and
`BROWSER_SUPERVISOR_CDP_URL`, but upstream should translate those into each
profile’s final `BROWSER_CDP_URL` when it writes managed profile `.env`
files. The same rule applies to profile Discord and webhook source vars.

This keeps profile-backed defaults and profile-specific env shaping close to
the bootstrap code that already owns managed profile `.env` generation.

## Risks / Trade-offs

- [Upstream and repo rollout can drift] → Land the contract change only once
  upstream is ready to populate managed profile `.env` files from container-wide
  inputs, or keep a short-lived compatibility path during rollout.
- [Missing env keys can silently break Hermes utilities] → Audit the current
  repo-projected keys and explicitly document which remain container-wide versus
  profile-specific.
- [Host-side cleanup could remove behavior still relied on by upstream] →
  Validate live Hermes behavior on `chill-penguin` before deleting any host-side
  profile patching logic.

## Migration Plan

1. Audit the env variables currently supplied through Hermes container
   `environment`, `environmentFiles`, runtime env generation, and profile
   patching.
2. Classify each variable as container-wide input or upstream-owned
   profile-specific output.
3. Update repo-managed Hermes wiring so `hermes-profile-env-sync` only maintains
   the container-wide env contract and no longer rewrites profile `.env` files.
4. Update upstream `ghostship-hermes` so bootstrap/profile startup writes the
   managed profile `.env` files from the supplied unchanged inputs,
   translated source vars, and generated defaults.
5. Validate live on `chill-penguin` that the final profile `.env` files contain
   the expected values without host-side post-processing.

## Open Questions

- Does upstream need one compatibility release that preserves host-patched
  values while the repo-side cleanup lands, or can the contract switch in one
  coordinated rollout?
- Should the repo continue to generate `runtime.env` as a file, or should more
  of those container-wide values move directly into the Podman unit
  environment once the contract is simplified?
