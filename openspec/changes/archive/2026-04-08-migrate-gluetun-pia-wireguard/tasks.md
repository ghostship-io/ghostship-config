## 1. Selector and bootstrap

- [x] 1.1 Add a daily selector helper and timer that read PIA credentials,
      fetch the live PIA server inventory, and filter candidates to
      PF-capable WireGuard regions.
- [x] 1.2 Add a two-phase benchmark so the selector uses a fast probe first
      and a short bounded speed test to choose the preferred daily winner.
- [x] 1.3 Add a startup bootstrap helper that consumes the cached winner,
      performs the PIA WireGuard bootstrap, and generates the runtime files or
      env vars Gluetun needs for its custom-provider path.

## 2. Gluetun runtime migration

- [x] 2.1 Update `modules/self-hosted/gluetun.nix` to replace the current
      native PIA OpenVPN configuration with the generated custom-provider
      WireGuard runtime path.
- [x] 2.2 Preserve PIA VPN-side port forwarding by wiring the required PIA
      forwarding credentials and selected `SERVER_NAMES` input into the new
      runtime.
- [x] 2.3 Keep `/srv/apps/gluetun:/gluetun` persistent and ensure the
      qBittorrent forwarded-port up/down hooks still reconcile the listen port
      after reconnects.

## 3. Monitoring and docs

- [x] 3.1 Update the Gluetun monitor to use generic port-forward state and to
      detect missing or drifted forwarded-port health explicitly.
- [x] 3.2 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe the
      new PIA WireGuard selector, required secrets, and verification flow.
- [x] 3.3 Validate the resulting host configuration with:
      `nixos-rebuild build --flake .#chill-penguin -L`
- [x] 3.4 Verify that port forwarding still updates qBittorrent/VueTorrent at
      startup and after Gluetun reconnects.
