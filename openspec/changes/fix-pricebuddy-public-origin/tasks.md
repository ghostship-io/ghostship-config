## 1. PriceBuddy origin wiring

- [ ] 1.1 Update `modules/self-hosted/pricebuddy.nix` so `pricebuddy-env-sync` writes `APP_URL=https://pricebuddy.ghostship.io` and `ASSET_URL=https://pricebuddy.ghostship.io` into `/srv/apps/pricebuddy/pricebuddy.env`.
- [ ] 1.2 Extend the managed PriceBuddy runtime verification to evaluate the running Laravel config and fail if app or asset URLs resolve to `http://localhost` or other non-HTTPS public origins.

## 2. Documentation and repo metadata

- [ ] 2.1 Update `README.md` to document that PriceBuddy’s managed runtime env includes the canonical public HTTPS origin for Laravel and Filament asset generation.
- [ ] 2.2 Update `CHANGELOG.md` and `AGENTS.md` with the durable fix and the repo memory that the public PriceBuddy hostname must stay explicit in the generated env.

## 3. Validation and rollout

- [ ] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.systemd.services.podman-pricebuddy.postStart --raw` and an appropriate `nixos-rebuild build --flake .#chill-penguin -L` validation path to confirm the managed service wiring evaluates cleanly.
- [ ] 3.2 Deploy the change to `chill-penguin` through the normal Git-based rebuild flow, then verify the public app no longer emits mixed-content Filament module imports and that `Add URL` works at `https://pricebuddy.ghostship.io/admin/products/3`.
