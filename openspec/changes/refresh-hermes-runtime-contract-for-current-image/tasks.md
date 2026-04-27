## 1. Refresh The Supported Hermes Contract

- [x] 1.1 Update the host-side Hermes env wiring and docs to remove
  `GHOSTSHIP_ROUTER_CHANNEL` from the supported downstream contract.
- [x] 1.2 Update the Hermes Discord routing contract so
  `GHOSTSHIP_CODEX_CHANNEL` remains the repo-owned forced Discord lane and
  non-Codex free-response sessions follow normal runtime routing.
- [x] 1.3 Capture the router as the normal primary path, Codex as the forced
  Discord channel lane, OpenCode Go as fallback, and
  `agent.reasoning_effort` `medium` as the supported managed default.
- [x] 1.4 Remove the stale downstream `CLOAKBROWSER_URL` export and document
  the image-owned native CloakBrowser path through `google-chrome` plus
  `AGENT_BROWSER_PROFILE`.

## 2. Refresh Persistence And Reset Guidance

- [x] 2.1 Update the `/nix` persistence contract to describe both first-boot
  seeding for an empty mount and boot-time reconciliation for reused non-empty
  `/nix`.
- [x] 2.2 Update the full-reset rollout contract so it explicitly wipes
  persisted auth, XDG state, custom skills, workspace data, and user-installed
  Nix state by deleting `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`,
  and `/srv/apps/hermes/nix`.
- [x] 2.3 Add the required post-reset follow-up that operators must re-auth
  Codex inside the fresh runtime before the forced Codex channel is usable.

## 3. Refresh Skill-Seeding Expectations

- [x] 3.1 Keep the repo-managed no-default-skill rule in place for
  `/home/hermes/.hermes/skills/`.
- [x] 3.2 Explicitly document that a full reset must not restore a repo-seeded
  `skill-creator`.
- [x] 3.3 Explicitly document that a full reset should allow the image's
  bundled upstream default skills to seed into `/home/hermes/.hermes/skills/`.

## 4. Verify The Updated Contract

- [x] 4.1 Validate the refreshed OpenSpec change with `openspec validate`.
- [x] 4.2 During implementation, verify the evaluated Hermes container env no
  longer documents or emits `GHOSTSHIP_ROUTER_CHANNEL` as supported contract
  state.
- [x] 4.3 During implementation, verify a full reset produces fresh home,
  workspace, and `/nix` state, bundled default skills, no repo-seeded
  `skill-creator`, and a runtime that requires fresh Codex auth.
- [x] 4.4 During implementation and rollout, verify the host actually applies
  the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image instead of
  reusing a stale cached image.

## 5. Apply Latest Upstream Follow-Up

- [x] 5.1 Update the forced Codex channel from `openai-codex/gpt-5.4` to
  `openai-codex/gpt-5.5` and record Firecrawl as the managed web backend.
- [x] 5.2 Add the upstream Bitwarden Password Manager CLI contract with
  `BITWARDENCLI_APPDATA_DIR=/home/hermes/.local/state/bitwarden-cli`.
- [x] 5.3 Add encrypted `hermes-secrets` stubs for Bitwarden, GitHub, and
  NVIDIA Build credentials.

## 6. Apply Upstream 36841a0 Env Contract Follow-Up

- [x] 6.1 Restore `GHOSTSHIP_CODEX_CHANNEL=1492841053642817606` and add
  `DISCORD_WEBHOOK_CHANNEL=1491229248856260799` to the Hermes container env.
- [x] 6.2 Add `OPENCODE_ZEN_API_KEY`, `ZENMUX_API_KEY`, and
  `ELECTRON_HUB_API_KEY` to the `hermes-secrets` catalog and encrypted stub
  file, with `OPENCODE_ZEN_API_KEY` staged from the current
  `OPENCODE_GO_API_KEY` value.
