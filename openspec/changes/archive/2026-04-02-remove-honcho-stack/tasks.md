## 1. Retire Honcho from the managed stack

- [x] 1.1 Remove `./honcho.nix` from `modules/self-hosted/default.nix` and delete the retired Honcho module implementation.
- [x] 1.2 Remove all remaining repo references to managed Honcho services, including Homepage and any service inventory that still advertises Honcho.

## 2. Remove dependent integrations and stale secrets

- [x] 2.1 Remove Hermes `HONCHO_*` environment wiring, legacy/shared Honcho compatibility-state management, and any retained `shared/honcho` tmpfiles or migration logic.
- [x] 2.2 Remove the Honcho-only `litellm-secrets` declaration and encrypted secret material, then verify no repo references to `litellm-secrets` remain.
- [x] 2.3 Update `openspec/specs/muximux-service-placement/spec.md`, `README.md`, `CHANGELOG.md`, and `AGENTS.md` to reflect that Honcho is no longer part of the supported Ghostship stack.

## 3. Validate the retired configuration

- [x] 3.1 Run `nix flake check --no-build -L` from the repo root.
- [x] 3.2 Run `nix eval .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath` to confirm the host configuration still evaluates after Honcho removal.

## 4. Deploy and clean host state

- [x] 4.1 Push `main`, then on `chill-penguin` run `git -C /home/nixos/nixos-config pull --ff-only origin main`, `nixos-rebuild build --flake .#chill-penguin -L`, and `./result/bin/switch-to-configuration switch`.
- [x] 4.2 Verify `podman-honcho.service`, `podman-honcho-db.service`, and `podman-honcho-redis.service` are no longer managed or running, and verify Hermes no longer exposes Honcho integration.
- [x] 4.3 Remove retired host state from `/srv/apps/honcho`, `/srv/apps/honcho-db`, `/srv/apps/honcho-redis`, and `/srv/apps/hermes/home/shared/honcho`, then confirm the cleanup on `chill-penguin`.
