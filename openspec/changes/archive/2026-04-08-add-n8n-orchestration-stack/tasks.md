## 1. n8n runtime module

- [x] 1.1 Create `modules/self-hosted/n8n.nix` for a single SQLite-backed `n8n` container with persistent state under `/srv/apps/n8n`, healthchecks, and the required browser/API environment.
- [x] 1.2 Import the new module from `modules/self-hosted/default.nix` and add any required `sops` secret declarations in `modules/self-hosted/secrets.nix`.
- [x] 1.3 Seed the required encrypted secret placeholders for the `n8n` runtime and Hermes API integration.
- [x] 1.4 Verify the host config evaluates the new service with `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.n8n.image` and any related secret or environment paths.

## 2. Hermes and dashboard integration

- [x] 2.1 Add the Hermes-facing `n8n` API environment so Hermes can reach the internal `n8n` service using a dedicated API key instead of the public hostname.
- [x] 2.2 Update `modules/self-hosted/homepage.nix` so Homepage `Services` includes an `n8n` entry tied to the managed container.
- [x] 2.3 Update `modules/self-hosted/muximux.nix` so the declarative Muximux layout emits `n8n` immediately after `Bazarr` in the dropdown.
- [x] 2.4 Verify the generated host config with `nix eval` or a host build so the `n8n` container, Homepage tile, and Muximux entry are all present in the evaluated `chill-penguin` configuration.

## 3. Documentation and rollout

- [x] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe the new `n8n` service, Hermes API access, and the required manual Muximux reorder on `chill-penguin`.
- [x] 3.2 Build and activate the updated configuration on `chill-penguin` with `ssh chill-penguin-root 'cd /home/nixos/nixos-config && nixos-rebuild build --flake .#chill-penguin -L'` followed by `ssh chill-penguin-root 'cd /home/nixos/nixos-config && ./result/bin/switch-to-configuration switch'`.
- [x] 3.3 Verify on `chill-penguin` that `n8n` is healthy, `/srv/apps/n8n` contains persisted state, Hermes can reach the internal `n8n` API path, and Homepage shows the new `n8n` tile.
- [x] 3.4 Manually reorder the live Muximux entry on `chill-penguin` so `n8n` appears directly under `Bazarr`, then verify the live portal layout matches the intended service order.
