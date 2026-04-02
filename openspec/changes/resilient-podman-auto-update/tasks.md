## 1. Resilient updater service

- [ ] 1.1 Add a wrapper script in `modules/self-hosted/common.nix` that runs native `podman auto-update --format json`, logs failed units, exits `0` for partial container failures, and preserves nonzero exits for hard updater failures.
- [ ] 1.2 Point `systemd.services.podman-auto-update` at the wrapper script while preserving the existing registry auth setup and network dependencies.
- [ ] 1.3 Change `systemd.timers.podman-auto-update.timerConfig.OnCalendar` from `daily` to `*-*-* 04:00:00` and keep `Persistent = true` plus `RandomizedDelaySec = "30m"`.

## 2. Nix verification

- [ ] 2.1 Parse-check the changed module with `nix-instantiate --parse modules/self-hosted/common.nix`.
- [ ] 2.2 Verify the generated service command with `nix eval .#nixosConfigurations.chill-penguin.config.systemd.services.podman-auto-update.serviceConfig.ExecStart`.
- [ ] 2.3 Verify the timer settings with `nix eval .#nixosConfigurations.chill-penguin.config.systemd.timers.podman-auto-update.timerConfig.OnCalendar`, `nix eval .#nixosConfigurations.chill-penguin.config.systemd.timers.podman-auto-update.timerConfig.RandomizedDelaySec`, and `nix eval .#nixosConfigurations.chill-penguin.config.systemd.timers.podman-auto-update.timerConfig.Persistent`.

## 3. Documentation

- [ ] 3.1 Update `README.md` to describe the resilient Podman auto-update behavior and the `04:00` to `04:30` scheduled window.
- [ ] 3.2 Update `CHANGELOG.md` with the new partial-failure handling and timer schedule.
- [ ] 3.3 Record the new auto-update behavior in `AGENTS.md` so future work preserves the resilient wrapper and `04:00` randomized window.

## 4. Host validation

- [ ] 4.1 Build or evaluate the host config as appropriate for this workspace, then apply it on `chill-penguin` using the repo's preferred deploy flow.
- [ ] 4.2 On `chill-penguin`, verify `systemctl status podman-auto-update.service --no-pager`, `systemctl status podman-auto-update.timer --no-pager`, and `systemctl list-timers podman-auto-update.timer --all --no-pager`.
- [ ] 4.3 Trigger a manual run on `chill-penguin` and confirm partial failures stay visible without failing the batch by checking `systemctl start podman-auto-update.service` and `journalctl -u podman-auto-update.service -n 200 --no-pager`.
