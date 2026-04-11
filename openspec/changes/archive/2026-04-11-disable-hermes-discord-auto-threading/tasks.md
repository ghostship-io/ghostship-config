## 1. Hermes Discord Configuration

- [ ] 1.1 Update `modules/self-hosted/hermes.nix` to set `DISCORD_REQUIRE_MENTION=true`.
- [ ] 1.2 Update `modules/self-hosted/hermes.nix` to set `DISCORD_AUTO_THREAD=false`.
- [ ] 1.3 Update `modules/self-hosted/hermes.nix` to set `DISCORD_FREE_RESPONSE_CHANNELS` to the assistant, operations, and supervisor channel IDs while keeping the general channel mention-only.

## 2. Documentation

- [ ] 2.1 Update `README.md` to document Hermes Discord mention policy, free-response channels, and the no-auto-thread behavior.
- [ ] 2.2 Update `CHANGELOG.md` with the Hermes Discord routing change.
- [ ] 2.3 Update `AGENTS.md` with any durable Hermes Discord routing or deploy verification guidance that should persist as repo memory.

## 3. Verification and Deploy

- [ ] 3.1 Run `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes.environment` and verify the Discord env vars are present with the expected values.
- [ ] 3.2 Deploy to `chill-penguin` with the repo-preferred flow: `git push origin main`, `ssh chill-penguin-root 'git -C /home/nixos/nixos-config pull --ff-only origin main'`, `ssh chill-penguin-root 'cd /home/nixos/nixos-config && nixos-rebuild build --flake .#chill-penguin -L'`, and `ssh chill-penguin-root 'cd /home/nixos/nixos-config && ./result/bin/switch-to-configuration switch'`.
- [ ] 3.3 Restart Hermes on `chill-penguin` and verify the running container reports `DISCORD_REQUIRE_MENTION=true`, `DISCORD_AUTO_THREAD=false`, and the expected `DISCORD_FREE_RESPONSE_CHANNELS` value.
