## 1. Update the Hermes runtime contract

- [ ] 1.1 Update `modules/self-hosted/hermes.nix` so Hermes mounts `/srv/apps/hermes/home` at `/home/hermes`, keeps `/srv/apps/hermes/workspace` at `/workspace`, and replaces the named `/nix` volume with a host bind mount under `/srv/apps/hermes`.
- [ ] 1.2 Add declarative host scaffolding for the new Hermes persistent paths, including the `/srv/apps/hermes/nix` bind target and the `/home/hermes/seeds/...` backing directories under `/srv/apps/hermes/home`.
- [ ] 1.3 Add the host-side `/nix` seed path so the persistent `/srv/apps/hermes/nix` tree is initialized from the current `ghcr.io/ghostship-io/ghostship-hermes:latest` image before Hermes starts with `/nix` mounted.

## 2. Wire Hermes profile gateway runtime env

- [ ] 2.1 Expand `modules/self-hosted/hermes.nix` environment wiring so Hermes bootstrap and the managed `assistant`, `operations`, and `supervisor` profile gateways receive the required Ghostship service URLs, service auth secrets, Discord settings, model-provider env, workflow secrets, and `BROWSER_CDP_URL`.
- [ ] 2.2 Extend `modules/self-hosted/secrets.nix` and the Hermes secret bundle wiring so the new Hermes runtime secrets are declared and loaded from `secrets.yaml` / `secrets.dec.yaml`.
- [ ] 2.3 Ensure the local Hermes router service receives `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_HTTP_REFERER`, `OPENROUTER_TITLE`, `OPENCODE_API_KEY`, and `OPENCODE_BASE_URL` along with the existing host and compatibility listener settings.

## 3. Update specs and documentation

- [ ] 3.1 Update the live Hermes spec under `openspec/specs/hermes-native-layout/spec.md` to replace the stale `/opt/data` and named-volume `/nix` contract with persisted `/home/hermes`, `/workspace`, and seeded host-mounted `/nix`.
- [ ] 3.2 Add the new live `openspec/specs/hermes-profile-gateway-runtime/spec.md` capability describing first-class profile gateways, `/home/hermes/seeds/...` runtime skill seeding, and required env propagation.
- [ ] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the current Hermes contract, the `/nix` seed expectation, the profile-gateway-first runtime model, and the runtime skill seed paths.

## 4. Verify and cut over `chill-penguin`

- [ ] 4.1 Run `nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel` to verify the updated host configuration evaluates and builds.
- [ ] 4.2 Activate `chill-penguin` with `nixos-rebuild build --flake .#chill-penguin` followed by `./result/bin/switch-to-configuration switch`, then verify Hermes mounts `/home/hermes`, `/workspace`, and the seeded host-backed `/nix`.
- [ ] 4.3 Verify the managed `assistant`, `operations`, and `supervisor` gateways, router, and dashboard are healthy on `chill-penguin`, and verify the Hermes-managed runtime sees the required Ghostship service env and `/home/hermes/seeds/...` paths.
