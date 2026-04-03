## 1. Service and browser-profile wiring

- [x] 1.1 Add `modules/self-hosted/changedetectionio.nix` and import it from `modules/self-hosted/default.nix` with the managed Podman container, persistent state, and internal-network defaults.
- [x] 1.2 Add the runtime helper and service ordering needed to resolve the dedicated CloakBrowser profile ID, generate `PLAYWRIGHT_DRIVER_URL`, and launch the profile before `changedetection.io` depends on it.
- [x] 1.3 Extend `modules/self-hosted/cloakbrowser.nix` so the bootstrap creates a new default `Changedetection` profile while preserving the existing `Direct` and `VPN` profiles.

## 2. Dashboard and documentation updates

- [x] 2.1 Update `modules/self-hosted/homepage.nix` so Homepage `Services` includes a `Changedetection` entry tied to the managed container.
- [x] 2.2 Update `modules/self-hosted/muximux.nix` so the generated Muximux layout places `Changedetection` immediately after `RSS-Bridge`.
- [x] 2.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the new service, the dedicated CloakBrowser profile, and any external ingress caveats.

## 3. Verification and rollout

- [ ] 3.1 Verify the Nix definitions with `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.changedetectionio.image --raw` and `nixos-rebuild build --flake .#chill-penguin -L`.
- [ ] 3.2 Activate on `chill-penguin`, then verify the live stack has the `Changedetection` CloakBrowser profile, a working profile-backed CDP URL, a Homepage `Services` tile, and a Muximux entry after `RSS-Bridge`.
