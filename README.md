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
- `codex`, `gemini`, `opencode`, and `openspec` all execute through `npx -y`
  so they resolve the latest upstream CLI at launch time instead of relying on
  a pinned npm install in the Nix store.
- The `openspec` wrapper defaults `openspec init` to
  `--tools codex,gemini,opencode --profile core` unless you pass explicit
  `--tools` or `--profile` values.
- Before `codex`, `gemini`, or `opencode` launches, the shared wrapper
  attempts a best-effort global `skills` refresh and, when started anywhere
  inside an OpenSpec repo, runs `openspec update` from the repo root so the
  latest slash-command scaffolding stays active.
- Before `opencode` launches, the wrapper also refreshes a generated OpenCode
  config under `XDG_STATE_HOME/opencode/programming-free-models.json` (or
  `~/.local/state/opencode/programming-free-models.json`) once per UTC day
  from OpenRouter's ranked programming free-model frontend endpoint and points
  `OPENCODE_CONFIG` at that generated file. The generated model list comes
  directly from the endpoint-derived programming free models and preserves the
  endpoint names with `(free)` rewritten to `(ghostship-free)`.
- Develop-host launcher configs now default to explicit YOLO or allow-all
  execution: Codex sets `approval_policy = "never"` with
  `sandbox_mode = "danger-full-access"`, Gemini sets
  `general.defaultApprovalMode = "yolo"`, and OpenCode's static Nix-managed
  config now only sets `permission = "allow"` while the wrapper-managed
  generated config owns the OpenRouter model list.
- Develop hosts keep `ssh-agent` on the fixed socket
  `/run/user/1000/ssh-agent` with a `12h` key lifetime, and they cache
  `sudo` credentials globally for `12h` so fresh agent PTYs do not prompt on
  every new shell.
- Those launcher defaults only take effect after the relevant develop-host
  NixOS rebuild or Home Manager switch applies the generated config files.
- Gemini also refreshes any managed Gemini extensions on launch. Wrapper-side
  update failures warn and continue instead of blocking the agent start.

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
native `HERMES_HOME=/home/hermes/.hermes` layout and relies on the image's
native entrypoint instead of a repo-side startup shim. Honcho is retired from
the Ghostship stack, so Hermes no longer exports `HONCHO_*` integration
settings and both Homepage and Muximux omit Honcho entirely. Hermes also
exposes a separate persistent workspace at `/home/hermes/workspace`, backed by
`/srv/apps/hermes/workspace` on the host, so operator-managed files do not have
to live inside the native Hermes home tree. Muximux keeps PriceBuddy on the
main bar immediately after Grimmory.

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
