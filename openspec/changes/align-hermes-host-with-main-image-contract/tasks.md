## 1. Realign The Hermes Host Contract

- [ ] 1.1 Update `modules/self-hosted/hermes.nix` so the Hermes container wiring follows the current `ghostship-hermes` `main` contract: remove in-container `systemd` startup calls, stop setting image-owned fixed env, and stop emitting legacy terminal env.
- [ ] 1.2 Update the Hermes Discord env wiring to carry `GHOSTSHIP_ROUTER_CHANNEL=1492841053642817606` and `GHOSTSHIP_CODEX_CHANNEL=1493462179725180959`, and render `DISCORD_FREE_RESPONSE_CHANNELS` with those two pinned channels plus `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`.
- [ ] 1.3 Replace `/srv/apps/hermes/home/seeds/...` staging with direct copy-if-missing seeding into `/srv/apps/hermes/home/.hermes/SOUL.md` and `/srv/apps/hermes/home/.hermes/skills/skill-creator/`, keeping the seeded runtime content writable by the Hermes runtime user.
- [ ] 1.4 Remove the host-side Hermes `/nix` seed-container bootstrap so `/srv/apps/hermes/nix` is mounted empty after the reset and the image's first-boot init path seeds `/nix` itself.

## 2. Update Docs And Durable Guidance

- [ ] 2.1 Update `README.md` to describe the current `ghostship-hermes` `main` workstation contract, the direct `.hermes` seed targets, and the exact destructive stop-reset-start rollout required for this image.
- [ ] 2.2 Update `AGENTS.md` so the repo memory reflects the current `main` contract: no `/home/hermes/seeds/...`, no in-container `systemd`, no host-side `/nix` seeding, and the exact router/Codex Discord lane contract.
- [ ] 2.3 Update `CHANGELOG.md` with the breaking Hermes host-contract realignment and the destructive persisted-state reset required for deployment.

## 3. Verify The New Contract And Rollout Path

- [ ] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes.environment --json` and verify the evaluated env omits image-owned fixed vars, includes `GHOSTSHIP_ROUTER_CHANNEL` and `GHOSTSHIP_CODEX_CHANNEL`, and renders the required five-channel `DISCORD_FREE_RESPONSE_CHANNELS` membership.
- [ ] 3.2 Run `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes.volumes --json` and verify the container still mounts `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` at `/home/hermes`, `/workspace`, and `/nix`.
- [ ] 3.3 Run `nixos-rebuild build --flake .#chill-penguin -L` and verify the host configuration builds with the updated Hermes wiring.
- [ ] 3.4 During deployment, stop the Hermes container, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then start the updated image and verify the live runtime has direct `.hermes` defaults, no repo-managed `/home/hermes/seeds/...` seam, image-seeded `/nix`, and the updated Discord env loaded on the running container.
