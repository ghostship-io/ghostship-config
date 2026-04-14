## Why

The current `chill-penguin` Hermes host wiring still reflects an older Ghostship-specific container contract: it stages seed content under `/home/hermes/seeds`, starts in-container `systemd` units, manually reseeds `/nix`, and omits the live `GHOSTSHIP_CODEX_CHANNEL` Discord lane from the supported env surface. The published `ghostship-hermes` `main` image has moved to an Ubuntu workstation contract owned by image-side `s6`, direct runtime state under `/home/hermes/.hermes`, and image-owned first-boot `/nix` seeding, so this repo needs a new breaking realignment before that image can be deployed safely.

## What Changes

- **BREAKING** Treat the current `ghostship-hermes` `main` workstation image contract as the source of truth for `chill-penguin` host wiring and stop relying on in-container `systemd` startup or host-side `/nix` bootstrapping.
- **BREAKING** Make the rollout contract for this image explicitly destructive: stop the Hermes container, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then start the updated image on clean persisted directories.
- **BREAKING** Remove the repo-managed seed staging seam under `/srv/apps/hermes/home/seeds/...` and write the repo-managed `SOUL.md` and `skill-creator` defaults directly into the intended runtime paths under `/srv/apps/hermes/home/.hermes/`.
- Update the Hermes runtime env contract to match the live upstream image: pass only downstream-facing runtime env, keep image-owned fixed env out of host wiring, and carry the router and Codex Discord channel vars expected by `main`.
- Require `DISCORD_FREE_RESPONSE_CHANNELS` to include `GHOSTSHIP_ROUTER_CHANNEL`, `GHOSTSHIP_CODEX_CHANNEL`, and the current three managed free-response channels so the pinned lanes are always usable without mention.
- Update OpenSpec, `README.md`, `CHANGELOG.md`, and `AGENTS.md` so the repo documents the destructive reset, direct `.hermes` seeding, and live upstream env/runtime contract consistently.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `hermes-single-agent-runtime`: Realign the supported runtime contract around the current upstream workstation image, image-owned `s6` supervision, and the destructive persisted-state reset required for this cutover.
- `hermes-utility-runtime-env`: Update the supported Hermes env surface to the current upstream runtime contract, including router and Codex channel env, pinned free-response membership, and the removal of host assumptions about generated root `.env` content.
- `hermes-discord-routing`: Require the managed free-response list to include both the router-pinned and Codex-pinned channels in addition to the existing three Ghostship free-response channels.
- `hermes-profile-souls`: Move the repo-managed `SOUL.md` seed target from `/home/hermes/seeds/SOUL.md` to the direct runtime path under `/home/hermes/.hermes/SOUL.md`.
- `hermes-profile-skill-seeds`: Move the repo-managed `skill-creator` seed target from `/home/hermes/seeds/skills/skill-creator/` to the direct runtime path under `/home/hermes/.hermes/skills/skill-creator/`.

## Impact

- Affected systems: `chill-penguin` server-host Hermes deployment, repo OpenSpec/docs, and the manual host rollout workflow for the new image.
- Affected code: `modules/self-hosted/hermes.nix`, Hermes seed assets under `modules/self-hosted/hermes-seeds/`, and any wiring that still assumes `/home/hermes/seeds`, in-container `systemd`, or host-driven `/nix` seeding.
- Manual cleanup: deployment for this change requires stopping Hermes and deleting `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before starting the updated image.
