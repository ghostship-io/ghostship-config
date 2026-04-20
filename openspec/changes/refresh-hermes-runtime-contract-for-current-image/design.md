## Context

The repo currently documents and wires a Hermes contract that was accurate for
an earlier upstream image but is no longer current. The drift is not only
cosmetic:

- local docs and specs still describe `GHOSTSHIP_CODEX_CHANNEL` as supported
  even though upstream removed that env from the runtime contract
- the local contract still assumes upstream-generated root `.env` defaults even
  though the current image treats runtime env and persisted `.hermes/.env` as
  downstream-owned inputs and does not rewrite that file
- local persistence notes treat `/nix` mostly as first-boot-seeded state,
  while current upstream supports reused non-empty `/nix` mounts by reconciling
  the image-managed default profile on every boot
- local runtime-contract docs do not clearly distinguish image-owned fixed env
  from supported downstream operator env
- local skill-seeding guidance says the repo does not seed default skills, but
  it does not capture the current upstream expectation that bundled default
  skills are seeded by the image into `/home/hermes/.hermes/skills/`

The user wants the next rollout to be a full reset, so the updated contract
must describe a fresh boot path rather than a drift-preserving migration.

## Goals / Non-Goals

**Goals**
- Realign the repo's Hermes runtime contract to the current upstream
  `ghostship-hermes` `main` image.
- Remove the retired Codex Discord lane from the documented downstream
  contract.
- Capture Codex as the normal primary model path after re-auth, with OpenCode
  fallback and router `agentic` custom-provider support.
- Clarify the exact semantics of a destructive reset and what state is lost.
- Clarify that a fresh reset relies on bundled upstream default skill seeding,
  not repo-seeded `skill-creator`.
- Describe the current `/nix` persistence contract accurately enough to support
  both clean resets and later reused mounts.
- Remove the stale downstream `CLOAKBROWSER_URL` contract so the host follows
  the image-owned native CloakBrowser browser path.

**Non-Goals**
- Implement the host-side Nix changes in this explore turn.
- Redesign upstream `ghostship-hermes`.
- Preserve existing persisted Hermes state through the next rollout.
- Add new repo-managed default skills on top of the image's bundled skill set.

## Decisions

### 1. Treat the current upstream workstation image docs as authoritative

The source of truth for this refresh is the current upstream `README.md`,
`docs/runtime-env.md`, `docs/workstation-image.md`, `AGENTS.md`, and the active
runtime-facing code paths on `main`.

Rationale:
- The user asked for the latest image changes, not historical compatibility.
- The current local contract is already known to have drifted.

### 2. Remove `GHOSTSHIP_CODEX_CHANNEL` from the supported downstream contract

The supported runtime contract will treat `GHOSTSHIP_ROUTER_CHANNEL` as the
only repo-owned forced Discord lane. Any stale `GHOSTSHIP_CODEX_CHANNEL` value
must be treated as retired contract drift.

Rationale:
- Upstream explicitly removed the managed Codex-pinned lane and its downstream
  env key.
- Keeping the key in this repo would document behavior the image no longer
  promises.

Alternatives considered:
- Keep documenting `GHOSTSHIP_CODEX_CHANNEL` because a local channel id still
  exists. Rejected because that channel can remain a normal free-response
  channel without being a supported forced-route contract.

### 3. Codex is the normal primary lane, not a special Discord override

The refreshed contract will capture `openai-codex/gpt-5.4` as the primary
managed model lane, `opencode-go/minimax-m2.7` as the configured fallback, the
router custom provider pinned to alias `agentic`, and `agent.reasoning_effort`
defaulting to `medium`.

Rationale:
- The user explicitly wants Codex primary now.
- Upstream documents Codex-primary runtime defaults and no longer treats Codex
  as a Discord-only forced lane.

### 4. Full reset means deleting all persisted workstation state

The destructive rollout contract will explicitly say that deleting
`/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`
removes:

- `/home/hermes/.hermes/auth.json` and any Codex auth
- operator-managed runtime config, memories, logs, and custom skills
- XDG/userland state under `.config`, `.local`, `.npm`, `.cargo`, `.rustup`,
  `.codex`, `.opencode`, `.ssh`, and similar
- workspace checkouts and local work products
- user-installed Nix packages and build outputs

The first boot after reset rebuilds only image-owned defaults plus whatever the
repo deliberately supplies through supported downstream env.

Rationale:
- The user explicitly wants a clean start.
- The reset semantics need to be unambiguous before implementation.

### 5. Fresh resets must rely on upstream bundled skill seeding

The repo will continue to avoid copying repo-managed default skills into
`/home/hermes/.hermes/skills/`, and the refreshed contract will say that a
fresh reset should rely on the image's bundled default skill seeding instead.
`skill-creator` must not survive as a repo-seeded default skill.

Rationale:
- The user explicitly wants `skill-creator` gone.
- Upstream now documents bundled skill seeding as part of normal boot.

Alternatives considered:
- Add a repo-managed allowlist of image-like default skills. Rejected because
  that would duplicate and drift from upstream image behavior.

### 6. `/nix` is both seedable-from-empty and reusable-when-non-empty

The refreshed contract will treat `/srv/apps/hermes/nix -> /nix` as:

- safe to recreate empty during a full reset because the image seeds `/nix`
  from `/opt/ghostship/nix-seed.tar.zst` on first boot
- safe to reuse later as a non-empty persisted mount because every boot
  reconciles the image-managed default profile at
  `/nix/var/nix/profiles/per-user/hermes/ghostship-defaults` without deleting
  user-managed Nix content

Rationale:
- This is one of the biggest functional deltas in the current upstream docs.
- It changes both the rollout story and the steady-state persistence story.

### 7. Apply the latest published image during the destructive reset

The rollout contract will explicitly require the host deployment to pull and
start the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image as
part of the reset, rather than relying on a stale cached local image.

Rationale:
- The user asked for the latest image applied, not just the latest local repo
  contract.
- A full reset against an old cached image would leave the runtime contract and
  the actual running image out of sync.
- The host module already intends latest-image behavior, but the rollout
  contract should say so explicitly.

Alternatives considered:
- Leave image freshness implicit because the service uses `pull = "always"`.
  Rejected because the deployment contract should still state that applying the
  latest image is part of the required rollout proof.

### 8. Fixed workstation env stay image-owned

The updated contract will treat path/layout/topology vars such as `HOME`,
`HERMES_HOME`, `XDG_*`, `NPM_CONFIG_PREFIX`, `CARGO_HOME`, `RUSTUP_HOME`,
`GHOSTSHIP_WORKSPACE_ROOT`, `GHOSTSHIP_*_PORT`, `GHOSTSHIP_*_HOST`,
`GHOSTSHIP_NIX_DEFAULT_PROFILE`, `GHOSTSHIP_TTYD_*`, `GHOSTSHIP_TERMINAL_CWD`,
`CAMOFOX_*`, `GHOSTSHIP_CAMOFOX_*`, `CAMOUFOX_CACHE_DIR`, and
`PLAYWRIGHT_BROWSERS_PATH` as unsupported downstream overrides.

Rationale:
- Upstream explicitly documents these as image-owned internals.
- The local host contract should not pretend to own them.

### 9. Native CloakBrowser stays image-owned

The refreshed contract will treat the stock local browser path as image-owned
native CloakBrowser launched through `google-chrome` with persistent profile
state under `/home/hermes/.local/state/cloakbrowser`. The host must not export
`CLOAKBROWSER_URL` or `CLOAKBROWSER_TOKEN` to Hermes as part of the supported
downstream contract.

Rationale:
- Upstream removed the manager/service-based browser contract on April 20.
- The live host still exported `CLOAKBROWSER_URL`, which no longer matches the
  supported runtime shape.

## Risks / Trade-offs

- [Risk] The new contract makes the next rollout more obviously destructive than
  before. -> Mitigation: state the reset consequences directly in specs/tasks.
- [Risk] Operators may still expect the retired Codex Discord lane to exist.
  -> Mitigation: make the removal explicit and treat any old channel as a
  normal free-response session instead of a forced lane.
- [Risk] Fresh reset boot may surprise operators by requiring re-auth before
  Codex-primary works again. -> Mitigation: include re-auth as an explicit
  post-reset task.
- [Risk] Upstream bundled skill seeding could change later. -> Mitigation:
  scope this contract refresh to the current image on `main`.

## Migration Plan

1. Update the host wiring and docs to remove `GHOSTSHIP_CODEX_CHANNEL` from the
   supported contract and keep only the router-pinned forced channel.
2. Update the documented runtime defaults so Codex is the normal primary lane,
   OpenCode is fallback, and router `agentic` remains the custom provider path.
3. Remove the stale downstream `CLOAKBROWSER_URL` export and document the
   image-owned native CloakBrowser path.
4. Update the persistence contract to describe both empty `/nix` seeding and
   reused non-empty `/nix` reconciliation.
5. During rollout, stop Hermes, remove `/srv/apps/hermes/home`,
   `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then let the
   image boot fresh.
6. Verify the fresh runtime has no repo-seeded `skill-creator`, does have the
   bundled upstream default skill set, and requires a fresh Codex auth before
   the normal primary lane is usable.

## Open Questions

- Whether the existing Ghostship Codex channel id should remain in
  `DISCORD_FREE_RESPONSE_CHANNELS` as a normal free-response channel after the
  forced-lane contract is removed. This change assumes "yes, optionally", but
  not as a required pinned-route contract.
