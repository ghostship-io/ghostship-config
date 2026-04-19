# Unified NixOS Configuration Fleet

This repository manages a small mixed NixOS fleet with one Apple Silicon
server, one AMD desktop, and two WSL2 development hosts. The repo is flake
based, uses Home Manager for the `nixos` user profile, and uses `ragenix`
logical-unit secret files.

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
- WSL-role hosts also enable `services.envfs` so Windows-side tools that
  connect into the guest can rely on hardcoded FHS paths such as
  `/usr/bin/bash`.
- System packages are reserved for host/admin essentials, service/runtime
  dependencies, and a small system-wide convenience baseline. Interactive shell
  tooling lives in Home Manager.
- Develop-role Home Manager packages include shared interactive CLI tools such
  as `gh` so GitHub workflows are available on every develop host after the
  relevant Home Manager or NixOS switch.

## Agent Launchers

- Develop hosts expose `codex`, `gemini`, `gemini-cli`, `opencode`,
  `agent-deck`, `agent-browser`, and `openspec` through Nix-managed wrapper
  scripts.
- Caveman full is enabled across the managed agent surfaces. Codex gets a
  managed SessionStart hook in `~/.codex/hooks.json`, Gemini reads the shared
  `~/.gemini/GEMINI.md` prompt and the managed Caveman extension, and OpenCode
  reads the shared `~/.config/opencode/AGENTS.md` prompt.
- The managed `agent-browser` wrapper defaults `AGENT_BROWSER_ENGINE=chrome`
  unless you override it explicitly, so local automation stays on the
  profile-capable Chrome engine even if upstream auto-selection changes.
- `codex`, `gemini`, `gemini-cli`, `opencode`, `agent-deck`, and `openspec`
  delegate to
  installed user-local CLIs under
  `/home/nixos/.local/share/ghostship-agent-tools/npm/bin`. The `openspec`
  wrapper falls back to `npx` only until maintenance bootstraps the managed
  binary.
- The `openspec` wrapper defaults `openspec init` to
  `--tools codex,gemini,opencode --profile core` unless you pass explicit
  `--tools` or `--profile` values.
- The managed `openspec` wrapper also defaults `DO_NOT_TRACK=1` and
  `OPENSPEC_TELEMETRY=0` so upstream OpenSpec `1.2.0` does not print noisy
  PostHog flush stack traces on hosts where telemetry egress is blocked.
- The wrapper also reapplies personal OpenSpec overrides after both
  `openspec init` and `openspec update`, but those overrides are append-only:
  the wrapper keeps the upstream generated workflow files and adds only three
  built-in Ghostship propose/apply/archive snippets on top.
- The Ghostship `propose` override creates or reuses the change
  worktree before planning, writes proposal/design/tasks from that worktree,
  and ends with a detailed overview of the full proposed change.
- The Ghostship `apply` override commits planning artifacts in the active
  worktree, continues implementation from that worktree, tracks issues found
  during apply, and ends with a detailed overview of the completed work and any
  proposal updates.
- The Ghostship `archive` override reconciles the change worktree back into
  `main`, commits the archive move there, removes the worktree, tries to leave
  `main` clean, and ends with a list of issues or follow-up work to consider
  next.
- `ghostship-agent-maintenance.service` owns automatic agent upkeep. Its
  timer runs on boot and every `4h`, with `Persistent=true` so missed runs
  fire after WSL resumes, and it installs or upgrades the user-local agent
  CLIs, ensures the configured `skills.sh` repos such as `caveman` are
  installed globally on each develop host, refreshes shared global skills,
  refreshes managed Gemini extensions, bootstraps `agent-browser` only when
  `~/.agent-browser` is missing, and carries an explicit shell-capable runtime
  path so npm and npx child processes can still spawn `sh` under systemd.
  Gemini's generated system settings also no longer declare the deprecated
  `experimental.plan` key, so the managed `gemini` and `gemini-cli` launchers
  stop warning about stale read-only system config after the relevant rebuild
  or switch. On Nix develop hosts that bootstrap intentionally treats system
  dependencies as already packaged and uses `agent-browser install` without
  `--with-deps` because the wrapper already supplies the required shared
  libraries. It also rewrites `~/.config/opencode/opencode.json` from
  OpenRouter's ranked programming free-model frontend endpoint with `(free)`
  rewritten to `(ghostship-free)` and rebuilds `agent-deck` from the latest
  upstream source release with the Ghostship web-mutations patch instead of
  pinning it in the flake.
- For immediate bootstrap as the logged-in user, run
  `ghostship-agent-maintenance`. The system service is still what runs on boot
  and every `4h`.
- Develop-host convergence also cleans the known stale `workmux set-window-status ...` entries from `~/.codex/hooks.json` so removed repo-managed tooling does not keep breaking Codex hooks. The cleanup preserves unrelated valid hooks, warns instead of rewriting malformed JSON, and takes effect after the relevant Home Manager or NixOS switch. Restart any already-running Codex sessions after the switch if they were holding the stale hook state open.
- Develop-host launchers now keep only the approval defaults: Codex prepends
  `--dangerously-bypass-approvals-and-sandbox` unless you pass explicit
  approval or sandbox flags, Gemini prepends `--yolo` unless you pass an
  explicit approval mode, and OpenCode keeps `permission = "allow"` in config.
- The user `opencode-web` service runs `opencode serve` through the Nix-managed
  Node binary and keeps `xdg-open` and `xdg-debug` intercepted with no-op
  shims under `~/.local/bin` so the headless systemd service does not try to
  launch a local browser. The managed unit binds only to `127.0.0.1:8421`.
- WSL develop hosts also enable a user `agent-deck-web` service that runs
  `agent-deck web --listen 127.0.0.1:8420`, so the web UI is available on the
  local host after the relevant Home Manager or NixOS switch. The maintained
  build carries a small local patch so browser-side session mutations stay
  enabled on current upstream releases.
- Develop hosts keep `ssh-agent` on the fixed socket
  `/run/user/1000/ssh-agent` with a `12h` key lifetime, and they cache
  `sudo` credentials globally for `12h` so fresh agent PTYs do not prompt on
  every new shell.
- Those launcher defaults only take effect after the relevant develop-host
  NixOS rebuild or Home Manager switch applies the generated config files.
- OpenSpec CLI updates are automatic through maintenance, but scaffold refresh
  is still manual. Run `openspec update .` inside an OpenSpec-enabled repo when
  you want to refresh slash-command assets.

## Shared Skills

- Shared repo-managed skills live under `home/config/skills/` and are linked
  into `~/.agents/skills/` on develop hosts. Managed `skills.sh` installs such
  as `caveman` also land under `~/.agents/skills/`, but they are maintained by
  `ghostship-agent-maintenance` instead of the repo-owned skill tree.
- The curated shared set is `nix`, `python`, `ssh`, `wsl2`, and a vendored
  `skill-creator` package pinned to the upstream `skill-creator`
  source at
  `vercel-labs/agent-browser` `v0.9.3`.
- Develop hosts also replace Codex's built-in
  `~/.codex/skills/.system/skill-creator` path with a managed symlink to
  `~/.agents/skills/skill-creator`, and `ghostship-agent-maintenance`
  reasserts that override after Codex CLI refreshes.
- Repo-local OpenSpec assets under `.codex/`, `.gemini/`, and `.opencode/`
  are a separate layer from the shared `~/.agents/skills` inventory.

## Self-Hosted Stack

The container stack lives in the flat
[`modules/self-hosted/default.nix`](/home/nixos/nixos-config/modules/self-hosted/default.nix)
inventory. Services use Podman, native healthchecks, and registry auto-update.
Only Plex exposes host ports; every other service is intended to stay on
internal networking and be reached through the reverse-proxy/tunnel path.

Key services include Plex, Homepage, Muximux, the `arr` stack,
qBittorrent/VueTorrent, SearXNG, RomM, Grimmory, Chaptarr, BookStack, CloakBrowser, Hermes,
PyLoad, RSS-Bridge, PriceBuddy, and n8n.

Gluetun on `chill-penguin` now uses PIA through Gluetun's custom-provider
WireGuard path instead of the native PIA OpenVPN mode. `podman-gluetun` starts
from the cached winner in `/srv/apps/gluetun/pia-wireguard-selection.json`, and
falls back to only a cheap provisional pick if no cache exists, before
regenerating `/run/secrets/gluetun-runtime.env`. A background
`gluetun-pia-selector` run starts 5 minutes after boot and reruns every 8 hours:
it pins selection to the PF-capable Vancouver PIA WireGuard servers, latency-screens those endpoints, benchmarks the top 10 Vancouver servers with a bounded generic HTTPS download test, and only restarts Gluetun when the new Vancouver winner is materially faster than the current cached server. The persisted `/srv/apps/gluetun` mount remains the
owner of Gluetun state and PIA's forwarded-port lease, while the
qBittorrent/VueTorrent up/down hooks plus the Gluetun monitor keep the listen
port reconciled after startup and reconnects. `podman-vuetorrent` also primes
`qBittorrent.conf` with Gluetun's current `tun0` IPv4 during service startup,
so qBittorrent does not spend its first boot window bound to the previous VPN
address after a Gluetun restart. The monitor still reconciles qBittorrent's
bound interface address to the live WireGuard `tun0` address after startup,
because qBittorrent 5.1.4 can stay disconnected if it only binds by interface
name after the VPN namespace changes. The Gluetun secret bundle must provide
PIA credentials (`PIA_USER`/`PIA_PASS` or legacy `OPENVPN_*` names) and
`HTTP_CONTROL_SERVER_API_KEY`, and does not require any application-specific benchmark credentials.

n8n runs as a single SQLite-backed workflow orchestrator in this repo and is intended to stay behind Cloudflare for browser access while Hermes talks to it over `ghostship_net`. Hermes should read its dedicated `N8N_API_KEY` from `n8n-secrets` rather than using a browser session. The live Muximux entry still needs a manual reorder on `chill-penguin` after deployment so it sits directly under Bazarr.

Chaptarr now extends the arr stack to books and audiobooks. It should mount the shared downloads root at `/downloads`, manage `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` as separate library roots, and stay visible in Homepage plus the Muximux dropdown immediately before Bazarr. Grimmory is still the primary reading and listening surface, so it also mounts both library roots. Public `chaptarr.ghostship.io` exposure remains part of the external Cloudflare/tunnel workflow rather than repo-managed ingress.

BookStack now adds a repo-managed wiki service on `chill-penguin` with app state under `/srv/apps/bookstack`, MariaDB state under `/srv/apps/bookstack-db`, and Homepage visibility in the `Services` group and a Muximux tile after Prowlarr. Keep `BOOKSTACK_APP_URL` pointed at the external `https://bookstack.ghostship.io` origin, and treat the initial in-app setup plus API token creation (`Authorization: Token <token_id>:<token_secret>`) as manual post-deploy operator steps instead of repo-managed bootstrap. Hermes now receives `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET` through the managed runtime env projection so the future utility contract is already wired once the secret bundle is populated. Public `bookstack.ghostship.io` exposure remains part of the external Cloudflare/tunnel workflow rather than repo-managed ingress.

CloakBrowser now seeds one default browser profile per Hermes profile
(`assistant`, `operations`, and `supervisor`) while keeping a dedicated
`Changedetection` profile for browser-backed watch checks. Ghostship also
periodically rechecks that `Changedetection` profile and relaunches it if the
manager stays healthy but the profile stops, because changedetection.io is not
profile-start-aware on its own.

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

Hermes now follows the current upstream `ghostship-hermes` `main` workstation contract on `chill-penguin`: `/srv/apps/hermes/home` mounts at `/home/hermes`, `/srv/apps/hermes/workspace` mounts at `/workspace`, and `/srv/apps/hermes/nix` mounts directly at `/nix`. The image owns its internal supervision, first-boot `/nix` seeding, and fixed runtime env, so `podman-hermes` no longer tries to start in-container `systemd` units or pre-populate `/nix` from the host. Ghostship passes the downstream-facing Discord env surface `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`, `DISCORD_FREE_RESPONSE_CHANNELS`, `GHOSTSHIP_ROUTER_CHANNEL`, and `GHOSTSHIP_CODEX_CHANNEL`; `DISCORD_HOME_CHANNEL` is pinned to `1491229269127598281`, and the free-response channel list is rendered to include the router lane `1492841053642817606`, the Codex lane `1493462179725180959`, and the current three Ghostship free-response channels `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`. The repo only seeds the Crush Crawfish `SOUL.md` default into `/srv/apps/hermes/home/.hermes/SOUL.md` when that runtime-owned path is missing; it does not seed any default skills into `/srv/apps/hermes/home/.hermes/skills/`. This image cutover is intentionally destructive: stop the Hermes container, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then start the updated image against clean persisted directories and let it reseed `/nix` and the runtime from scratch. Muximux keeps PriceBuddy in the dropdown immediately after Bazarr.

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
development hosts and on Apple Silicon Linux systems. On this host's current Nix
`2.31.3` stack the shell export path is order-sensitive: keep `git` before
`age` in the default shell package list or `nix print-dev-env` and `direnv` can
fail with `get-env.sh failed to produce an environment`. After changing the
default shell, run `direnv reload` or start a fresh shell to pick up the updated
environment.

Apply the built generation:

```fish
./result/bin/switch-to-configuration switch
```

Build a different host without switching:

```fish
nixos-rebuild build --flake .#chill-penguin
```

## Secrets

- `secrets/catalog.nix` is the source of truth for the encrypted file layout,
  recipient groups, file metadata, and exported fields.
- `secrets/recipients.nix` defines operator and host SSH recipients. Runtime
  decryption uses SSH host `ed25519` keys; human edit access uses the dedicated
  passwordless non-default key `~/.ssh/id_ed25519_ragenix`.
- `secrets/files/**/*.age` stores the logical-unit encrypted env files consumed
  by NixOS through `ragenix`.

Helper commands:

```bash
secret-edit-keygen         # create ~/.ssh/id_ed25519_ragenix if missing
secrets-list-keys          # list logical-unit catalog keys
secret-list                # inspect catalog entries and recipient groups
secret-edit <logical-id>   # edit one logical-unit .age file directly
secret-rekey               # rekey all .age files after recipient changes
```

Normal operator flow is direct per-file editing with `secret-edit
<logical-id>`. Use `secrets-list-keys` or `secret-list` to find the logical
unit you need, then run `secret-rekey` only when recipient membership changes.

## Bootstrap

Use `sudo ./bootstrap.sh NEW_HOSTNAME [output-dir]` from a temporary NixOS or
WSL2 install to capture a temporary host-intake bundle. `bootstrap.sh` requires
`sudo`, tries `hostnamectl`, then falls back to `hostname` or
`/proc/sys/kernel/hostname` for a best-effort live hostname update. On WSL2 it
also ensures `/etc/ssh/ssh_host_ed25519_key.pub` exists, because those hosts
may not generate the SSH host key by default.

The bundle contains:

- `manifest.json`
- `facts.json`
- `hardware-configuration.nix`
- `public/ssh_host_ed25519_key.pub`
- `bootstrap-notes.md`

Supported onboarding flow:

1. Run `sudo ./bootstrap.sh NEW_HOSTNAME`.
2. Copy the output directory into `references/host-intake/NEW_HOSTNAME/` in the repo.
3. Ask Codex to integrate that staged intake bundle into `hosts/`, `flake.nix`, and `secrets/recipients.nix`.
4. Review and commit the repo changes.
5. Remove the temporary `references/host-intake/NEW_HOSTNAME/` directory.

## Notes

- `nh` is installed as a convenience tool, but the documented workflow in this
  repo is native `nix` and `nixos-rebuild`.
- WSL hosts expose wrapped `wsl-open`, `win-powershell`, a Windows
  notification bridge for `notify-send`, and a `hard`-mounted NFS automount at
  `/mnt/z`. They keep `envfs` for Linux/FHS paths such as `/usr/bin/bash`, but
  do not import the Windows PATH into the Linux shell, so use explicit
  `/mnt/c/...` paths or repo-managed wrappers for Windows tools. WSL activation
  now stops the `/mnt/z` automount and unmounts any live NFS mount before
  reloading the generated mount units so host switches do not fail on stale
  `/mnt/z` mount state.
- WSL hosts cap `nix.settings.max-jobs` at `8` so concurrent flake shells,
  agent sessions, and host builds do not wedge `nix-daemon` under `auto`
  parallelism.
- WSL hosts also cap `nix.settings.cores` at `4` so each build job cannot
  fan out across all reported host threads and recreate the same memory-pressure
  stalls from inside a smaller job queue.
- Login sessions raise the soft `nofile` limit to `65536` to keep busy shells,
  editors, and agent workflows from running into a low default descriptor cap.
