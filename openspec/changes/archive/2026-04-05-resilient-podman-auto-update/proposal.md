## Why

The self-hosted stack already uses native Podman auto-update, but a single
container restart failure currently causes the shared `podman-auto-update`
systemd unit to fail even when other containers updated successfully. That
makes routine updates look broken and obscures the difference between partial
service failures and real updater failures.

## What Changes

- Add a resilient wrapper around native `podman auto-update` so container-level
  restart failures are reported in logs without failing the entire scheduled
  update unit.
- Preserve hard failures for updater problems such as auth, registry access, or
  malformed output that prevent trustworthy update results.
- Change the self-hosted Podman update timer from `daily` to a fixed `04:00`
  schedule while keeping the existing randomized delay window.
- Update repo documentation and agent memory for the new schedule and failure
  semantics.

## Capabilities

### New Capabilities
- `podman-auto-update-resilience`: Defines resilient scheduled Podman image
  updates for self-hosted server containers, including partial-failure handling
  and the 04:00 randomized timer window.

### Modified Capabilities
- None.

## Impact

- Affected systems: server hosts that run the self-hosted Podman stack,
  especially `chill-penguin`; no develop-host or Home Manager behavior changes.
- Affected code: `modules/self-hosted/common.nix` plus supporting
  documentation in `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Host activation implications: the updated systemd service and timer will take
  effect on the next host rebuild/switch; no manual cleanup is expected beyond
  normal activation.
