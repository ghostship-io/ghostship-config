## Context

`modules/self-hosted/hermes.nix` currently reflects a transitional Ghostship-specific contract rather than the live `ghostship-hermes` `main` contract. The host module still injects image-owned fixed env, stages repo-managed defaults under `/srv/apps/hermes/home/seeds/...`, manually reseeds `/srv/apps/hermes/nix` from a throwaway container mount, and calls `systemctl` inside the container to start runtime services.

The live upstream image now owns those seams differently. The current published workstation image is Ubuntu-based, uses image-side supervision, persists `/home/hermes`, `/workspace`, and `/nix`, seeds empty `/nix` on first boot, treats container runtime env as the primary downstream contract, and expects the router and Codex Discord lanes through `GHOSTSHIP_ROUTER_CHANNEL` and `GHOSTSHIP_CODEX_CHANNEL`. The user also wants this cutover to be fully destructive: stop the container, wipe every persisted Hermes directory, then start the new image from clean persisted paths.

## Goals / Non-Goals

**Goals:**
- Realign the `chill-penguin` Hermes host module to the current `ghostship-hermes` `main` contract.
- Remove repo-managed startup assumptions that conflict with the current workstation image, especially in-container `systemd` startup and host-driven `/nix` seeding.
- Seed the repo-managed `SOUL.md` and `skill-creator` defaults directly into `/srv/apps/hermes/home/.hermes/...` instead of staging them under `/srv/apps/hermes/home/seeds/...`.
- Encode the exact Discord channel contract: preserve the existing router channel, add the Codex channel, and ensure both are included in `DISCORD_FREE_RESPONSE_CHANNELS` alongside the current three Ghostship free-response channels.
- Make the destructive rollout path explicit in OpenSpec and docs so deploys follow the required stop-reset-start sequence.

**Non-Goals:**
- Redesign or patch the upstream `ghostship-hermes` image itself.
- Preserve compatibility with the old `/home/hermes/seeds/...` staging contract.
- Preserve in-container `systemd` service control as a fallback path.
- Migrate old persisted Hermes auth, workspace, or `/nix` state in place; this cutover intentionally discards it.
- Anticipate future upstream image proposals that are not yet part of the current `main` contract.

## Decisions

### 1. Treat the current upstream `main` image as authoritative
The repo will align to the current live `ghostship-hermes` `main` contract exactly as published and observed in the local upstream checkout. Host wiring will stop trying to preserve transitional Ghostship-specific seams once they conflict with that contract.

Rationale:
- The user explicitly wants the repo ready for the new image on `main`, not for older transitional behavior.
- Keeping the host module on a partially obsolete contract creates avoidable deployment risk.
- Matching `main` directly gives a single source of truth for future debugging.

Alternatives considered:
- Preserve the current host-side compatibility shims for seeds, startup, and `/nix` seeding. Rejected because those shims directly contradict the current image contract.
- Design around upstream in-progress proposals instead of `main`. Rejected because the user explicitly chose current `main` as the source of truth.

### 2. Make the rollout explicitly destructive
The deployment contract for this image cutover will stop the Hermes container, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then start the new image from clean persisted directories.

Rationale:
- The user explicitly requires a full reset of all persisted Hermes directories before deployment.
- Current persisted state contains contract drift: old seed paths, old runtime files, and potentially stale managed tooling state.
- A clean reset is lower-risk than inventing a one-off migration for runtime state the user does not want to preserve.

Alternatives considered:
- Preserve `/workspace` or `/nix` while resetting only `/home/hermes`. Rejected because the user asked for a complete reset and the image contract treats all three mounts as one coherent persisted workstation state set.
- Attempt an in-place migration. Rejected because it preserves stale state and increases rollout complexity.

### 3. Seed repo-managed defaults directly into `.hermes`
Repo-managed `SOUL.md` and `skill-creator` content will be copied directly into `/srv/apps/hermes/home/.hermes/SOUL.md` and `/srv/apps/hermes/home/.hermes/skills/skill-creator/`, with copy-if-missing behavior and runtime-writable ownership.

Rationale:
- The user explicitly wants seeds to go directly into the intended runtime directory.
- This removes the stale `/home/hermes/seeds/...` seam entirely.
- Copy-if-missing keeps the repo responsible for the initial default while preserving operator ownership after first seed.

Alternatives considered:
- Keep staging under `/srv/apps/hermes/home/seeds/...` and rely on the image to consume it. Rejected because that is not the target contract.
- Always overwrite runtime `SOUL.md` and `skills/` on startup. Rejected because it would destroy operator edits after first boot.

### 4. Let the image seed empty `/nix`
The host module will stop manually mounting a seed container and rsyncing `/nix`. Instead, the host will provide an empty recreated `/srv/apps/hermes/nix` bind mount and let the image's first-boot init path seed it.

Rationale:
- The current upstream image already documents and implements first-boot `/nix` seeding.
- Removing host-side `/nix` bootstrap reduces duplicate logic and one more image drift seam.
- This keeps the repo aligned with the image's supported startup path.

Alternatives considered:
- Keep the current host-side `/nix` rsync path as a safety net. Rejected because duplicate seeding logic becomes another unsupported contract surface.

### 5. Narrow host env wiring to the supported downstream surface
The host module will stop setting image-owned fixed env such as `HOME`, `HERMES_HOME`, `GHOSTSHIP_WORKSPACE_ROOT`, and the old terminal vars. It will keep only supported downstream runtime env plus the repo-managed utility projections.

Rationale:
- The current upstream contract treats fixed env as image-owned and unsupported for downstream override.
- Removing those host-side settings reduces drift and makes the container environment easier to reason about.
- The repo still needs to own utility env projection and selected auth injection, but not the image's internal layout env.

Alternatives considered:
- Keep setting the fixed vars redundantly because the values match today. Rejected because redundant ownership becomes drift when upstream changes those values later.

### 6. Encode the router and Codex Discord lanes explicitly
The host module will carry both `GHOSTSHIP_ROUTER_CHANNEL=1492841053642817606` and `GHOSTSHIP_CODEX_CHANNEL=1493462179725180959`, and it will render `DISCORD_FREE_RESPONSE_CHANNELS` to include both pinned channels plus the current three Ghostship free-response channels.

Rationale:
- The current upstream `main` image expects both pinned channel env names.
- The user explicitly confirmed the exact router channel, Codex channel, and required free-response membership.
- Rendering the full merged list in repo-managed wiring prevents accidental omission of the pinned lanes.

Alternatives considered:
- Keep only the current three free-response channels and let router/Codex lanes exist outside that list. Rejected because the user explicitly wants both pinned lanes included.
- Infer free-response membership from router/Codex vars at runtime. Rejected because explicit rendered membership is clearer and easier to verify.

## Risks / Trade-offs

- [Risk] The destructive rollout deletes persisted auth, sessions, workspace contents, local tooling state, and operator-installed `/nix` packages. -> Mitigation: document the reset explicitly in proposal/tasks/docs and treat it as a required manual deployment step.
- [Risk] Direct `.hermes` seeding could still drift from future upstream expectations if `main` changes again. -> Mitigation: scope this change to current `main` only and document that the repo follows the live upstream contract as its source of truth.
- [Risk] Copy-if-missing seeding may leave stale operator-modified defaults after first boot. -> Mitigation: this is intentional; preserving runtime ownership after first seed is preferable to silently overwriting operator changes.
- [Risk] Removing host-side `/nix` seeding makes image startup responsible for that path entirely. -> Mitigation: verify the live image's documented first-boot `/nix` seeding path in implementation validation.
- [Risk] Discord routing can still drift if the pinned channels are not rendered into the free-response list exactly. -> Mitigation: encode the exact merged list in repo-managed wiring and verify it via evaluated container env output.

## Migration Plan

1. Update `modules/self-hosted/hermes.nix` so the host no longer stages `/home/hermes/seeds/...`, no longer starts in-container `systemd` units, no longer pre-seeds `/nix`, and renders only the supported downstream env surface for the current image.
2. Update the active Hermes OpenSpec deltas, `README.md`, `CHANGELOG.md`, and `AGENTS.md` so the repo documents the current workstation-image contract consistently.
3. Evaluate or build the updated `chill-penguin` configuration and verify the generated Hermes container env omits image-owned fixed vars, includes `GHOSTSHIP_ROUTER_CHANNEL` and `GHOSTSHIP_CODEX_CHANNEL`, and renders `DISCORD_FREE_RESPONSE_CHANNELS` with the required five-channel membership.
4. During deployment, stop the Hermes container, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then start the updated image against recreated empty persisted directories.
5. Verify the live runtime after deployment: no repo-managed `/home/hermes/seeds/...` seam, repo defaults present directly under `/home/hermes/.hermes/`, empty-reset `/nix` successfully reseeded by the image, and the updated Discord env loaded on the running container.
6. Roll back only by redeploying an older host revision and reinitializing fresh persisted Hermes directories again; this change does not preserve the deleted runtime state for in-place rollback.

## Open Questions

- None currently.
