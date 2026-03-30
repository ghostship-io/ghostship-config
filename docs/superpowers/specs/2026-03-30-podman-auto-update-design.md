# Podman Auto-Update Design

## Goal

Keep the self-hosted Podman stack on `chill-penguin` current by:

- setting `pull = "always";` on every self-hosted OCI container
- marking all self-hosted containers for native Podman auto-update
- adding a daily systemd timer that runs Podman's native auto-update flow

The first version does not implement external notifications for failed
restarts.

## Scope

- Applies to the self-hosted Podman stack under `modules/self-hosted/`
- Covers all current containers defined through
  `virtualisation.oci-containers.containers.*`
- Adds a daily update service/timer using native Podman auto-update
- Leaves failure visibility in systemd/journal only for now

## Non-Goals

- No notification integration yet (email, ntfy, Gotify, Discord, Slack, etc.)
- No version pinning or digest pinning
- No selective opt-out for stateful or infrastructure containers
- No custom per-container digest comparison script

## Current State

The repo currently defines self-hosted containers individually under
`modules/self-hosted/*.nix`.

Container pull behavior currently relies on the upstream NixOS
`virtualisation.oci-containers` default:

- each container defaults to `pull = "missing"`
- containers are recreated through their generated `podman-*.service` units
- no daily image-update timer exists in the self-hosted stack

This means a running host can stay on stale cached images even when tags like
`latest` have moved upstream.

## Proposed Design

### 1. Explicit Pull Policy On Every Container

Every self-hosted container module should set:

- `pull = "always";`

This should be done explicitly in each module rather than only via an
implicit shared override, because the user asked for the setting to be added
to every container and checked in.

### 2. Native Podman Auto-Update Labels

Every self-hosted container should carry Podman's native auto-update label so
the daily update job can discover and process it.

Use:

- `labels."io.containers.autoupdate" = "registry";`

This matches the current image-based registry workflow used by the stack.

### 3. Daily Auto-Update Service And Timer

Add a service and timer in `modules/self-hosted/common.nix`:

- service runs `${pkgs.podman}/bin/podman auto-update`
- timer runs once per day
- unit should depend on normal system startup/network availability

Podman's native auto-update behavior should:

- check whether a newer remote image exists for a labeled container
- pull the updated image when needed
- restart/recreate only containers whose image changed
- leave unchanged containers alone

This is preferred over a custom updater script because it is the platform's
intended update path and avoids duplicating Podman's own update logic.

### 4. Failure Handling In First Pass

For the first pass:

- no external notification target is configured
- failed updates/restarts are surfaced through:
  - `systemctl status podman-auto-update.service`
  - `journalctl -u podman-auto-update.service`
  - affected `podman-<name>.service` units

The design should preserve space for a later follow-up that adds a
notification hook after the update service runs and inspects failed units.

## Files To Change

- Modify: `modules/self-hosted/common.nix`
- Modify: every self-hosted container module under `modules/self-hosted/`
  that defines `virtualisation.oci-containers.containers.*`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `AGENTS.md`

Expected container modules in scope:

- `modules/self-hosted/bazarr.nix`
- `modules/self-hosted/bentopdf.nix`
- `modules/self-hosted/cloakbrowser.nix`
- `modules/self-hosted/cloudflared.nix`
- `modules/self-hosted/convertx.nix`
- `modules/self-hosted/flaresolverr.nix`
- `modules/self-hosted/gluetun.nix`
- `modules/self-hosted/grimmory-db.nix`
- `modules/self-hosted/grimmory.nix`
- `modules/self-hosted/hermes.nix`
- `modules/self-hosted/homepage.nix`
- `modules/self-hosted/it-tools.nix`
- `modules/self-hosted/metube.nix`
- `modules/self-hosted/muximux.nix`
- `modules/self-hosted/nzbget.nix`
- `modules/self-hosted/omnitools.nix`
- `modules/self-hosted/plex-auto-languages.nix`
- `modules/self-hosted/plex.nix`
- `modules/self-hosted/prowlarr.nix`
- `modules/self-hosted/pyload.nix`
- `modules/self-hosted/radarr.nix`
- `modules/self-hosted/recyclarr.nix`
- `modules/self-hosted/romm-db.nix`
- `modules/self-hosted/romm.nix`
- `modules/self-hosted/searxng-valkey.nix`
- `modules/self-hosted/searxng.nix`
- `modules/self-hosted/sonarr.nix`
- `modules/self-hosted/tautulli.nix`
- `modules/self-hosted/vuetorrent.nix`

## Verification Plan

### Static Verification

- parse-check touched modules with `nix-instantiate --parse`
- build the self-hosted host:
  - `nixos-rebuild build --flake .#chill-penguin`

### Evaluation Verification

After evaluation, confirm:

- each self-hosted container resolves with `pull = "always"`
- each self-hosted container resolves with
  `labels."io.containers.autoupdate" = "registry"`
- the daily `podman-auto-update.service` and timer are generated

### Runtime Verification

After switching on host, verify:

- `systemctl status podman-auto-update.timer`
- `systemctl list-timers | grep podman-auto-update`
- manual update run succeeds:
  - `systemctl start podman-auto-update.service`
- inspect logs:
  - `journalctl -u podman-auto-update.service -n 100 --no-pager`

## Risks

- Because `pull = "always";` is applied everywhere, any service restart can
  become an upgrade event even outside the daily timer.
- Stateful services and infrastructure services are intentionally included,
  which increases the chance of upstream regressions affecting core stack
  availability.
- Native Podman auto-update may restart containers in an order that exposes
  dependency sensitivity between services, especially around `gluetun` and
  containers sharing or depending on its namespace.
- Without notifications, failed post-update restarts require checking
  systemd/journal to detect promptly.

## Recommendation

Implement the native Podman auto-update path with explicit `pull = "always";`
and Podman auto-update labels on every self-hosted container. This matches the
user's freshness-first preference while keeping the first version relatively
simple and aligned with Podman's intended update model.
