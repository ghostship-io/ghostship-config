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
- `openspec/`: repo-local spec, change, and task artifacts shared by Codex,
  Gemini, and OpenCode
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

## Agent Launchers

- Develop hosts expose `codex`, `gemini`, `opencode`, `agent-browser`, and
  `openspec` through Nix-managed wrapper scripts.
- `codex`, `gemini`, and `opencode` now delegate to installed user-local
  CLIs under `/home/nixos/.local/share/ghostship-agent-tools/npm/bin`, while
  `openspec` still executes through its Nix-managed `npx` wrapper.
- The `openspec` wrapper defaults `openspec init` to
  `--tools codex,gemini,opencode --profile core` unless you pass explicit
  `--tools` or `--profile` values.
- The wrapper also reapplies personal OpenSpec overrides after both
  `openspec init` and `openspec update`, but those overrides are append-only:
  the wrapper keeps the upstream generated workflow files and adds only three
  built-in Ghostship propose/apply/archive snippets on top.
- The Ghostship OpenSpec flow now keeps proposal/design/tasks work on `main`,
  creates or reuses `.worktrees/<change-name>/` during `apply` after those
  planning artifacts are committed on `main`, and uses `archive` to reconcile
  any matching worktree back into `main`, commit the archive move there, and
  remove the worktree.
- `ghostship-agent-maintenance.service` owns automatic agent upkeep. Its
  timer runs on boot and every `4h`, with `Persistent=true` so missed runs
  fire after WSL resumes, and it installs or upgrades the user-local agent
  CLIs, refreshes shared global skills, refreshes managed Gemini extensions,
  bootstraps `agent-browser` only when `~/.agent-browser` is missing, and
  rewrites `~/.config/opencode/opencode.json` from OpenRouter's ranked
  programming free-model frontend endpoint with `(free)` rewritten to
  `(ghostship-free)`.
- For immediate bootstrap as the logged-in user, run
  `ghostship-agent-maintenance`. The system service is still what runs on boot
  and every `4h`.
- Develop-host launchers now keep only the approval defaults: Codex prepends
  `--dangerously-bypass-approvals-and-sandbox` unless you pass explicit
  approval or sandbox flags, Gemini prepends `--yolo` unless you pass an
  explicit approval mode, and OpenCode keeps `permission = "allow"` in config.
- Develop hosts keep `ssh-agent` on the fixed socket
  `/run/user/1000/ssh-agent` with a `12h` key lifetime, and they cache
  `sudo` credentials globally for `12h` so fresh agent PTYs do not prompt on
  every new shell.
- Those launcher defaults only take effect after the relevant develop-host
  NixOS rebuild or Home Manager switch applies the generated config files.
- OpenSpec scaffold refresh is manual again. Run `openspec update .` inside an
  OpenSpec-enabled repo when you want to refresh slash-command assets.

## Shared Skills

- Shared repo-managed skills live under `home/config/skills/` and are linked
  into `~/.agents/skills/` on develop hosts.
- The curated shared set is `nix`, `python`, `ssh`, `wsl2`, and a vendored
  `skills-creator` package pinned to the upstream `skill-creator`
  source at
  `vercel-labs/agent-browser` `v0.9.3`.
- Repo-local OpenSpec assets under `.codex/`, `.gemini/`, and `.opencode/`
  are a separate layer from the shared `~/.agents/skills` inventory.

## Self-Hosted Stack

The container stack lives in the flat
[`modules/self-hosted/default.nix`](/home/nixos/nixos-config/modules/self-hosted/default.nix)
inventory. Services use Podman, native healthchecks, and registry auto-update.
Only Plex exposes host ports; every other service is intended to stay on
internal networking and be reached through the reverse-proxy/tunnel path.

Key services include Plex, Homepage, Muximux, the `arr` stack,
qBittorrent/VueTorrent, SearXNG, RomM, Grimmory, CloakBrowser, Hermes,
PyLoad, RSS-Bridge, and PriceBuddy.

RomM currently runs cleanly on the upstream `rommapp/romm:latest` image
without the old post-start bundle rewrite. Validate future iframe regressions
against a live unpatched container before reintroducing any frontend patch.
Muximux embeds RomM through a same-origin `/romm/` reverse proxy because the
public `romm.ghostship.io` origin sits behind Cloudflare Access and is not a
stable iframe target.
The current mitigation keeps RomM's bundle untouched and injects an
iframe-only shim from the Muximux proxy immediately before RomM's main module
script. Do not switch that back to a generic `<head>` prepend; it broke the
asset base and left RomM looping on chunk imports.
The proxy also injects a real `<base href="/romm/">` into RomM's HTML so newer
bundles that ship an empty Vite `BASE_URL` still boot the router under `/romm/`
instead of briefly landing on the in-app not-found route.

SearXNG is intended to run as an internal-only search hub on `ghostship_net`
with a Nix-managed max-open engine allowlist, and internal consumers such as
Hermes should use the container-network address `http://searxng:8080`. The
engine inventory is regenerated in `podman-searxng` `preStart` so curated
engine changes and container restarts stay coupled during `nixos-rebuild`.

PriceBuddy seeds a `pricebuddy@ghostship.io` / `pricebuddy` login and reads a
persistent agent API token from the `pricebuddy-secrets` bundle. The live
`/srv/apps/pricebuddy/pricebuddy-agent.env` file contains a shell-safe
`PRICEBUDDY_API_TOKEN="id|token"` bearer line for direct API use. The host
token-sync now strips any previously persisted token ID before rewriting that
file, and the managed `podman-pricebuddy` post-start path verifies the app env
files, scraper reachability, and final bearer-token shape without treating
upstream auth-route bugs or third-party Cloudflare challenges as Ghostship env
regressions.

Hermes writes its durable state to `/srv/apps/hermes/home` through the image's
workstation-style `HERMES_HOME=/opt/data` layout and relies on the image's
native entrypoint instead of a repo-side startup shim. Honcho is retired from
the Ghostship stack, so Hermes no longer exports `HONCHO_*` integration
settings and both Homepage and Muximux omit Honcho entirely. Hermes also mounts
`/srv/apps/hermes/workspace` directly at `/workspace`, which is now the
canonical in-container work-products path. The container also persists `/nix`
through a named Podman volume so Hermes-managed Nix installs and build outputs
survive container replacement. Muximux keeps PriceBuddy in the dropdown
immediately after Bazarr.

## Usage

Run system-changing commands from a root shell or direct root SSH session.

Build the current host:

```fish
nixos-rebuild build --flake .#(hostname)
```

Enter the repo shell with direnv or Nix:

```fish
direnv allow
# or
nix develop
```

The flake exposes a default Linux dev shell so `use flake` works on the WSL
development hosts and on Apple Silicon Linux systems.

Apply the built generation:

```fish
./result/bin/switch-to-configuration switch
```

Build a different host without switching:

```fish
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
  and an NFS automount at `/mnt/z`. Prefer `/mnt/c/...` for Windows files.
- WSL hosts cap `nix.settings.max-jobs` at `8` so concurrent flake shells,
  agent sessions, and host builds do not wedge `nix-daemon` under `auto`
  parallelism.
- WSL hosts also cap `nix.settings.cores` at `4` so each build job cannot
  fan out across all reported host threads and recreate the same memory-pressure
  stalls from inside a smaller job queue.
- Login sessions raise the soft `nofile` limit to `65536` to keep busy shells,
  editors, and agent workflows from running into a low default descriptor cap.
