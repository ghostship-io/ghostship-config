## 1. Retire the provider from desired state

- [ ] 1.1 Remove the `Server2` / `eu.usenetprime.com` wiring from `modules/self-hosted/nzbget.nix` and delete the retired `NZBGET_SERVER2_*` credentials from `secrets.dec.yaml`.
- [ ] 1.2 Update the active OpenSpec delta and `CHANGELOG.md` to record that the managed NZBGet provider set now excludes UsenetPrime.

## 2. Verify and reconcile the live host

- [ ] 2.1 Validate the `chill-penguin` Nix config from the change worktree with a concrete command such as `nix eval .#nixosConfigurations.chill-penguin.config.networking.hostName`.
- [ ] 2.2 Manually remove the retired `Server2.*` entries from `/srv/apps/nzbget/nzbget.conf` on `chill-penguin`, restart `podman-nzbget.service`, and verify the live host no longer references `usenetprime` or `NZBGET_SERVER2` in the active config and generated secret file.
