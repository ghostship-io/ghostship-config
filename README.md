# Unified NixOS Configuration Fleet

This repository manages a small mixed NixOS fleet with one Apple Silicon
server, one AMD desktop, and two WSL2 development hosts. The repo is flake
based, uses Home Manager for the `nixos` user profile, and uses `sops-nix`
for secrets.

## Hosts

| Host | Role | Notes |
| --- | --- | --- |
| `launch-octopus` | `develop + wsl` | Primary WSL2 development environment |
| `armored-armadillo` | `develop + wsl` | Secondary WSL2 development environment |
| `chill-penguin` | `server` | Apple Silicon self-hosted server |
| `boomer-kuwanger` | `server` | AMD desktop with a minimal server-style user profile |

## Layout

- `flake.nix`: shared host construction and top-level outputs
- `hosts/`: per-host configuration and role assignment
- `modules/common/`: shared NixOS base modules
- `modules/develop/`: develop-role system tooling and wrappers
- `modules/wsl/`: WSL-only system integration
- `modules/self-hosted/`: flat Podman service inventory
- `home/profiles/`: Home Manager base, server, develop, and WSL profile layers

## Role Model

- Server-role hosts use a minimal Home Manager profile and default to `bash`.
- All Bash shells, including root, get the same global completion and history
  defaults from the NixOS layer.
- Develop-role hosts use the richer interactive profile and default to `fish`.
- WSL-role hosts layer WSL-specific mounts, Windows interop, and notification
  helpers on top of the develop profile.
- System packages are reserved for host/admin essentials, service/runtime
  dependencies, and a small system-wide convenience baseline. Interactive shell
  tooling lives in Home Manager.

## Self-Hosted Stack

The container stack lives in the flat
[`modules/self-hosted/default.nix`](/home/nixos/nixos-config/modules/self-hosted/default.nix)
inventory. Services use Podman, native healthchecks, and registry auto-update.
Only Plex exposes host ports; every other service is intended to stay on
internal networking and be reached through the reverse-proxy/tunnel path.

Key services include Plex, Homepage, Muximux, the `arr` stack,
qBittorrent/VueTorrent, SearXNG, RomM, Grimmory, CloakBrowser, Hermes,
PyLoad, RSS-Bridge, and PriceBuddy.

PriceBuddy seeds a `pricebuddy@ghostship.io` / `pricebuddy` login and reads a
persistent agent API token from the `pricebuddy-secrets` bundle into
`/srv/apps/pricebuddy/pricebuddy-agent.env`.

## Usage

Run system-changing commands from a root shell or direct root SSH session.

Build the current host:

```bash
nixos-rebuild build --flake .#$(hostname)
```

Apply the built generation:

```bash
./result/bin/switch-to-configuration switch
```

Build a different host without switching:

```bash
nixos-rebuild build --flake .#chill-penguin
```

## Secrets

- `secrets.yaml` is the encrypted source of truth.
- `secrets.dec.yaml` is the ignored plaintext mirror used for inspection and
  edits before re-encryption.
- Service bundles use `*-secrets` names and are consumed directly by the
  relevant modules.

Helper commands:

```bash
secrets-edit secrets.yaml
secrets-list-keys
secrets-add-key <age1...> [system-name]
secrets-reencrypt
generate-age-key
secrets-get-public-key
```

## Bootstrap

Use `./bootstrap.sh NEW_HOSTNAME` from a temporary NixOS install to generate
the host registration JSON and ensure `/etc/nix/secrets/age.key` exists. Then
register the host, add it to `flake.nix`, commit the new host files, and apply
the configuration with `nixos-rebuild`.

## Notes

- `nh` is installed as a convenience tool, but the documented workflow in this
  repo is native `nix` and `nixos-rebuild`.
- WSL hosts expose `wsl-open`, a Windows notification bridge for `notify-send`,
  a `~/win-home` symlink, and an NFS automount at `/mnt/z`.
