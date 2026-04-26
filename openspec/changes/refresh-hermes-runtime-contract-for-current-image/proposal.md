## Why

The current `chill-penguin` Hermes runtime contract in this repo drifted behind
the live `ghostship-hermes` `main` image. Upstream has since removed the
managed Discord Codex-pinned lane and retired `GHOSTSHIP_CODEX_CHANNEL`,
documented Codex as the normal primary model path with OpenCode fallback,
clarified that fixed workstation env are image-owned internals, documented
boot-time reconciliation for reused non-empty `/nix` mounts, and made bundled
upstream skill seeding under `/home/hermes/.hermes/skills/` part of the normal
first-boot contract.

The user also wants the next rollout to be a full destructive reset: wipe the
persisted Hermes home, workspace, and `/nix` state, start from a clean image
boot, ensure no repo-seeded `skill-creator` survives, and rely on the image's
default bundled skills instead.

## What Changes

- **BREAKING** Remove `GHOSTSHIP_CODEX_CHANNEL` from the supported downstream
  Hermes contract and treat `GHOSTSHIP_ROUTER_CHANNEL` as the only
  repo-owned forced Discord lane.
- **BREAKING** Treat Codex `openai-codex/gpt-5.5` as the normal primary model
  path for the managed runtime, with direct `opencode-go/minimax-m2.7` as the
  configured fallback lane, Firecrawl as the managed web backend, and the local
  router exposed as custom provider `agentic`.
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
  `GITHUB_TOKEN`, and `NVIDIA_BUILD_API_KEY`.
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
- `hermes-discord-routing`: Remove the retired Codex lane from the supported
  Discord contract and keep only the router-pinned forced lane.
- `hermes-profile-skill-seeds`: Make the no-repo-seeded-skill contract explicit
  for full resets while preserving upstream bundled skill seeding.

## Impact

- Affected systems: `chill-penguin` Hermes deployment, repo OpenSpec runtime
  contract, and the manual reset-and-reseed rollout path.
- Affected code: `modules/self-hosted/hermes.nix`, related docs, and any
  deployment logic that still sets `GHOSTSHIP_CODEX_CHANNEL`, assumes generated
  root `.env` content, or reasons about `/nix` as seed-once-only state.
- Manual follow-up: after the full reset, operators must re-auth Codex inside
  the fresh persisted home before the normal Codex-primary lane works again.
