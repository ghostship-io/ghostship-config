# Paseo Container Design

## Goal

Add a dedicated self-hosted Paseo container to `chill-penguin` that matches the
proven OpenChamber runtime platform while keeping all Paseo state isolated.
Paseo will orchestrate Codex and OpenCode. Google Antigravity CLI will be
installed and maintained alongside them for direct use, without being exposed
as a Paseo provider.

## Architecture

- Build a repo-owned `localhost/ghostship-paseo` OCI image with Nix and systemd
  as PID 1.
- Run the application as the unprivileged `paseo` user with UID/GID 3000.
- Persist home, workspace, Docker, and isolated Nix state under
  `/srv/apps/paseo`.
- Run container system services for setup, `nix-daemon`, the UID 3000 user
  manager, nested Docker, bootstrap hooks, the Paseo daemon, maintenance, and
  health monitoring.
- Serve `paseo daemon start --foreground --web-ui` on port 6767 inside
  `ghostship_net`. Do not publish a host port.
- Leave Cloudflare route creation outside this change. The route will use
  Cloudflare Access as the external authentication boundary; Paseo itself will
  have no password.

## Tooling and Updates

Install current upstream releases into a persistent user-owned tool prefix:

- `@getpaseo/cli`
- `@openai/codex`
- `opencode-ai`, retaining the architecture-specific fallback used by
  OpenChamber
- Google Antigravity CLI (`agy`) through Google's checksum-validating installer

A four-hour systemd timer downloads updates and records changed versions. A
separate timer applies a queued daemon restart only when Paseo's global agent
list contains no `initializing` or `running` agents. The gate is checked twice
to reduce races. Unknown activity leaves the restart queued. Paseo's immediate
self-update path is not used by automated maintenance.

## Persistent User Runtime

The Paseo user receives a persistent systemd user manager and D-Bus session,
plus a Linux Secret Service for Antigravity credentials. Persisted user units
live under `~/.config/systemd/user` and are managed through
`paseo-user-units`. The container also provides:

- isolated unprivileged Nix builds through an internal root-owned daemon
- nested Docker
- bootstrap, pre-daemon, and doctor hook directories
- Cloudflared Quick Tunnel helpers for project-local web services
- file-backed logs

Codex and Antigravity authentication are one-time interactive operator steps.
Their credentials remain in the persisted Paseo home.

## Secrets and Configuration

Add a dedicated `paseo.env` runtime projection containing the applicable
GitHub, OpenRouter, OpenCode, and Bitwarden fields already used by the agent
containers. Do not add or project a Paseo password.

`paseo-apply-config` validates Paseo and Antigravity JSON, Codex TOML, and
OpenCode's resolved configuration. It snapshots configuration only, restarts
the daemon through a narrow sudoers rule, verifies health and provider
discovery, and restores the last-good configuration if recovery fails.
Sessions, pairings, workspaces, and credentials are never rolled back.

## Health and Shutdown

The daemon service restarts on failure. A periodic monitor checks the systemd
service, Paseo `/api/health`, Codex/OpenCode discovery, and Antigravity binary
availability. Recovery is deferred when Paseo reports active work. Container
health tolerates long first boot and does not kill a degraded runtime when
activity is unknown.

Reuse OpenChamber's proven systemd shutdown target chain and bounded stop
ordering so Podman can stop the container without SIGKILL. Limit the Paseo
daemon and its child agents with `MemoryHigh=12G` and `MemoryMax=16G`; this
leaves headroom beside OpenChamber's 40 GiB maximum on the 62 GiB host.

## Repository Integration

- Add `modules/self-hosted/paseo.nix` and import it from the self-hosted module
  aggregator.
- Add Homepage and Muximux entries for `https://paseo.ghostship.io`.
- Update `README.md`, `CHANGELOG.md`, and `VERSION`.
- Do not refactor the live OpenChamber or Codex container modules as part of
  this change.

## Verification

1. Evaluate and build the `chill-penguin` configuration and Paseo image.
2. Commit and push the repo changes.
3. Pull, build, and switch on `chill-penguin`.
4. Prove host Podman health and every required in-container system service.
5. Verify the web UI, `/api/health`, provider discovery, CLI versions, user
   systemd, Nix, Docker, mounts, and live secret inheritance.
6. Fault-inject a daemon failure and confirm recovery.
7. Prove queued updates defer during active work and apply when idle.
8. Exercise configuration rejection and rollback.
9. Restart the container and confirm clean shutdown without SIGKILL.
10. Complete and persist Codex and Antigravity OAuth interactively as the final
    operator step.
