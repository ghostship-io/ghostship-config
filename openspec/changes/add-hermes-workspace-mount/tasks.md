## 1. Hermes workspace mount

- [ ] 1.1 Update `modules/self-hosted/hermes.nix` to declare `/srv/apps/hermes/workspace` and add the direct bind mount to `/home/hermes/workspace` while keeping the existing `/home/hermes/.hermes` mount unchanged.
- [ ] 1.2 Extend Hermes tmpfiles rules so `/srv/apps/hermes/workspace` is created declaratively with the same host ownership model as the rest of the Hermes data root.

## 2. Documentation and spec alignment

- [ ] 2.1 Update `README.md` to document the separate Hermes home and workspace host paths.
- [ ] 2.2 Update `CHANGELOG.md` and `AGENTS.md` to record the persistent Hermes workspace contract and the expectation that it lives at `/srv/apps/hermes/workspace`.

## 3. Validation and host rollout

- [ ] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath` to verify the host still evaluates with the Hermes workspace mount.
- [ ] 3.2 Push `main`, then on `chill-penguin` run `git -C /home/nixos/nixos-config pull --ff-only origin main`, `nixos-rebuild build --flake .#chill-penguin -L`, and `./result/bin/switch-to-configuration switch`.
- [ ] 3.3 Verify the live Hermes container exposes `/home/hermes/workspace` and that it is backed by `/srv/apps/hermes/workspace` on the host.
