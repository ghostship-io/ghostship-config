## 1. Reproduce and classify the live regression

- [x] 1.1 Disable or bypass the current RomM `postStart` iframe patch on `chill-penguin` long enough to start the unmodified 4.8.0 image.
- [x] 1.2 Verify whether the unpatched image still fails in the actual Muximux iframe path and record whether the failure is an iframe regression, a startup issue, or both.
- [x] 1.3 Capture the live evidence needed for the change notes, including the service state, relevant RomM logs, and the active frontend/runtime behavior in Muximux.

## 2. Replace the brittle mitigation path

- [x] 2.1 Update `modules/self-hosted/romm.nix` so RomM startup no longer depends on a single exact minified bundle string or hashed asset filename.
- [x] 2.2 Implement the proven Muximux same-origin `/romm/` reverse proxy in the repo and make it survive container restarts and Podman IP churn.
- [x] 2.3 If the unpatched image does not regress, keep the obsolete iframe patch path removed and document why the remaining Muximux failure is outside RomM.

## 3. Verify and document the host change

- [x] 3.1 Evaluate and build the host config with `nix eval --impure .#nixosConfigurations.chill-penguin.config.systemd.services.podman-romm.postStart` and `nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel -L`.
- [x] 3.2 Apply the updated config on `chill-penguin`, then verify `systemctl status podman-romm.service --no-pager -l`, `podman ps`, and the iframe behavior against the live served RomM app through Muximux.
- [x] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` with any durable RomM upgrade and iframe-mitigation workflow changes discovered during the fix.
