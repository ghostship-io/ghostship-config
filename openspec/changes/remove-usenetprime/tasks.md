## 1. Retire the provider from desired state

- [x] 1.1 Remove the `Server2` / `eu.usenetprime.com` wiring from `modules/self-hosted/nzbget.nix` and delete the retired `NZBGET_SERVER2_*` credentials from the local `secrets.dec.yaml` plaintext mirror.
- [x] 1.2 Update the active OpenSpec delta and `CHANGELOG.md` to record that the managed NZBGet provider set now excludes UsenetPrime.

## 2. Verify and reconcile the live host

- [x] 2.1 Validate the `chill-penguin` Nix config from the change worktree with a concrete command such as `nix eval .#nixosConfigurations.chill-penguin.config.networking.hostName`.
- [x] 2.2 Manually remove the retired `Server2.*` entries from `/srv/apps/nzbget/nzbget.conf` on `chill-penguin`, restart `podman-nzbget.service`, and verify the live host no longer references `usenetprime` in the active NZBGet config.
