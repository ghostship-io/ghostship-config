## 1. Refresh The Supported Hermes Contract

- [ ] 1.1 Update the host-side Hermes env wiring and docs to remove
  `GHOSTSHIP_CODEX_CHANNEL` from the supported downstream contract.
- [ ] 1.2 Update the Hermes Discord routing contract so only
  `GHOSTSHIP_ROUTER_CHANNEL` remains a repo-owned forced Discord lane and
  non-router free-response sessions follow normal runtime routing.
- [ ] 1.3 Capture Codex as the normal primary model lane, OpenCode as fallback,
  router `coding` as the custom provider path, and `agent.reasoning_effort`
  `medium` as the supported managed default.

## 2. Refresh Persistence And Reset Guidance

- [ ] 2.1 Update the `/nix` persistence contract to describe both first-boot
  seeding for an empty mount and boot-time reconciliation for reused non-empty
  `/nix`.
- [ ] 2.2 Update the full-reset rollout contract so it explicitly wipes
  persisted auth, XDG state, custom skills, workspace data, and user-installed
  Nix state by deleting `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`,
  and `/srv/apps/hermes/nix`.
- [ ] 2.3 Add the required post-reset follow-up that operators must re-auth
  Codex inside the fresh runtime before the normal primary lane is usable.

## 3. Refresh Skill-Seeding Expectations

- [ ] 3.1 Keep the repo-managed no-default-skill rule in place for
  `/home/hermes/.hermes/skills/`.
- [ ] 3.2 Explicitly document that a full reset must not restore a repo-seeded
  `skill-creator`.
- [ ] 3.3 Explicitly document that a full reset should allow the image's
  bundled upstream default skills to seed into `/home/hermes/.hermes/skills/`.

## 4. Verify The Updated Contract

- [ ] 4.1 Validate the refreshed OpenSpec change with `openspec validate`.
- [ ] 4.2 During implementation, verify the evaluated Hermes container env no
  longer documents or emits `GHOSTSHIP_CODEX_CHANNEL` as supported contract
  state.
- [ ] 4.3 During implementation, verify a full reset produces fresh home,
  workspace, and `/nix` state, bundled default skills, no repo-seeded
  `skill-creator`, and a runtime that requires fresh Codex auth.
- [ ] 4.4 During implementation and rollout, verify the host actually applies
  the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image instead of
  reusing a stale cached image.
