## Why

The current `chill-penguin` Hermes runtime contract in this repo drifted behind
the live `ghostship-hermes` `main` image. Upstream has since restored the
managed Discord Codex-pinned lane through `GHOSTSHIP_CODEX_CHANNEL`, retired
`GHOSTSHIP_ROUTER_CHANNEL`, documented the local router as the normal primary
path with OpenCode Go fallback,
clarified that fixed workstation env are image-owned internals, documented
boot-time reconciliation for reused non-empty `/nix` mounts, and made bundled
upstream skill seeding under `/home/hermes/.hermes/skills/` part of the normal
first-boot contract.

The user also wants the next rollout to be a full destructive reset: wipe the
persisted Hermes home, workspace, and `/nix` state, start from a clean image
boot, ensure no repo-seeded `skill-creator` survives, and rely on the image's
default bundled skills instead.

## What Changes

- **BREAKING** Remove `GHOSTSHIP_ROUTER_CHANNEL` from the supported downstream
  Hermes contract and treat `GHOSTSHIP_CODEX_CHANNEL` as the repo-owned forced
  Discord Codex lane.
- **BREAKING** Treat the local router as the normal primary model path, with
  Codex `openai-codex/gpt-5.5` reserved for the forced Discord Codex channel,
  direct `opencode-go/minimax-m2.7` as the configured paid fallback lane,
  Firecrawl as the managed web backend, and the local router exposed as custom
  provider `agentic`.
- **BREAKING** Make the rollout contract explicitly destructive again: stop
  Hermes, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and
  `/srv/apps/hermes/nix`, then let the latest published image reseed fresh
  runtime state.
- Update the runtime env contract to match the current upstream image:
  downstream only owns operator env, fixed workstation env stay image-owned,
  and the image no longer rewrites `/home/hermes/.hermes/.env` for the host.
- Remove the stale downstream `CLOAKBROWSER_URL` expectation so Hermes follows
  the image-owned native CloakBrowser path through `google-chrome` and the
  persistent `AGENT_BROWSER_PROFILE`.
- Add the image-managed Bitwarden CLI appdata env and encrypted
  operator-filled stubs for `BW_CLIENTID`, `BW_CLIENTSECRET`, `BW_PASSWORD`,
  `GITHUB_TOKEN`, `NVIDIA_BUILD_API_KEY`, `OPENCODE_ZEN_API_KEY`,
  `ZENMUX_API_KEY`, and `ELECTRON_HUB_API_KEY`.
- Update the `/nix` contract to describe both safe first-boot seeding for an
  empty mount and boot-time reconciliation of the image-managed default profile
  for reused non-empty `/nix`.
- Clarify that the repo must not seed `skill-creator` or any other repo-owned
  default skill into `/home/hermes/.hermes/skills/`, while a fresh reset must
  still allow the image to seed its bundled upstream default skills there.
- Update the OpenSpec runtime contract so a full reset explicitly discards
  persisted Codex auth, custom skills, XDG state, workspace contents, and
  user-installed Nix packages; operators must re-auth Codex after the reset.

## Capabilities

### New Capabilities
- `hermes-runtime-model-defaults`: Define the supported managed model order and
  reasoning defaults for the current upstream workstation image.

### Modified Capabilities
- `hermes-single-agent-runtime`: Clarify what a full reset wipes and what the
  fresh runtime rebuilds from image-owned defaults.
- `hermes-native-layout`: Update the `/nix` persistence contract for both empty
  and reused persisted mounts.
- `hermes-utility-runtime-env`: Narrow the supported downstream env contract to
  the current image-owned vs operator-owned split.
- `hermes-discord-routing`: Remove the retired router lane from the supported
  Discord contract and keep the Codex-pinned forced lane.
- `hermes-profile-skill-seeds`: Make the no-repo-seeded-skill contract explicit
  for full resets while preserving upstream bundled skill seeding.

## Impact

- Affected systems: `chill-penguin` Hermes deployment, repo OpenSpec runtime
  contract, and the manual reset-and-reseed rollout path.
- Affected code: `modules/self-hosted/hermes.nix`, related docs, and any
  deployment logic that still sets `GHOSTSHIP_ROUTER_CHANNEL`, assumes generated
  root `.env` content, or reasons about `/nix` as seed-once-only state.
- Manual follow-up: after the full reset, operators must re-auth Codex inside
  the fresh persisted home before the forced Codex Discord lane works again.
