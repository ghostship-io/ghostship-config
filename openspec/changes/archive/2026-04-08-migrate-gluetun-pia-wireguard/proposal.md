## Why

`chill-penguin` currently runs Gluetun against Private Internet Access over
OpenVPN with a hard-coded region, and the user is seeing download throughput
that is too slow for the existing qBittorrent and NZBGet stack. We need to
migrate to PIA over WireGuard while preserving VPN-side port forwarding and add
an automated selector that can periodically discover a faster
port-forward-capable server instead of freezing the stack to one stale choice.

## What Changes

- **BREAKING** Replace the current native PIA OpenVPN Gluetun setup with a
  custom-provider WireGuard bootstrap flow for PIA.
- Add a daily selector service that fetches PIA's live server inventory,
  filters for port-forward-capable WireGuard regions, probes candidates, runs a
  short bounded speed test against the best few servers, and caches the
  preferred target for Gluetun to use.
- Add startup logic that consumes the last cached preferred server when Gluetun
  starts or restarts, bootstraps the PIA WireGuard runtime metadata, and falls
  back safely when the cached winner is no longer valid.
- Preserve the existing qBittorrent port-forwarding behavior by keeping
  `/srv/apps/gluetun:/gluetun` persistent and continuing to drive qBittorrent's
  listen port from Gluetun's forwarded-port events.
- Upgrade Gluetun monitoring so the host can distinguish container liveness,
  VPN health, and port-forwarding failures, and react when the forwarded port
  disappears or drifts from qBittorrent's configured port.
- Update repo documentation and operations notes to describe the new WireGuard
  selector, bootstrap flow, secret inputs, and host-side validation path.

## Capabilities

### New Capabilities
- `gluetun-pia-wireguard-runtime`: Define the dynamic PIA WireGuard bootstrap,
  daily fastest-server selection, and port-forward-aware runtime contract for
  Gluetun on `chill-penguin`.

### Modified Capabilities
- `muximux-service-placement`: Clarify operator-facing validation assumptions
  for the Gluetun-backed downloads stack when the VPN runtime behavior changes.

## Impact

- Affected code: `modules/self-hosted/gluetun.nix` and any new helper scripts
  or static assets needed to select and bootstrap PIA WireGuard custom-provider
  settings.
- Affected docs: `README.md`, `CHANGELOG.md`, and `AGENTS.md`.
- Affected system: the `chill-penguin` server host and the Gluetun, qBittorrent
  (VueTorrent), and NZBGet runtime path behind it.
- Host activation impact: this change requires a rebuild and switch on
  `chill-penguin`, plus updated `gluetun-secrets` content for the new
  WireGuard/bootstrap inputs.
