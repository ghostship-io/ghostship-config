## 1. Reproduce and classify the remaining live regression

- [x] 1.1 Disable or bypass the current RomM `postStart` iframe patch on `chill-penguin` long enough to start the unmodified 4.8.0 image.
- [x] 1.2 Verify that the same-origin Muximux `/romm/` path still fails in the real `/#RomM` iframe flow and record whether the failure is a hard crash, blank render, or startup issue.
- [x] 1.3 Capture the live evidence needed for the change notes, including direct `/romm/` versus `/#RomM` behavior, relevant RomM logs, the active iframe source, and the current browser runtime error.

## 2. Replace the brittle mitigation path

- [x] 2.1 Update `modules/self-hosted/romm.nix` so RomM startup no longer depends on a single exact minified bundle string or hashed asset filename.
- [x] 2.2 Keep the proven Muximux same-origin `/romm/` reverse proxy in the repo and make it survive container restarts and Podman IP churn.
- [x] 2.3 Implement a managed Muximux iframe-only runtime shim and inject it before RomM's main module loads without rewriting RomM's served bundle on disk.
- [x] 2.4 Scope the shim to framed loads and stable browser/runtime APIs only, and remove any temporary live RomM bundle rewrite once the shim path is active.

## 3. Verify and document the host change

- [ ] 3.1 Evaluate the updated Muximux config and build the target host system with the new shim asset and injection path.
- [ ] 3.2 Apply the updated config on `chill-penguin`, remove any ad hoc live RomM file edits, then verify `systemctl status podman-romm.service --no-pager -l`, `podman ps`, direct `/romm/`, and the iframe behavior at `/#RomM`.
- [x] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` with the shim-based mitigation workflow and any durable live-validation lessons from the new fix.
