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
| `boomer-kuwanger` | `server + emulation` | AMD HX100G dedicated ES-DE emulation PC |

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
- WSL-role hosts import the Windows PATH for desktop interop and use explicit
  writable FHS shims for the hardcoded `/bin/...` and `/usr/bin/...` paths
  needed by Windows-side tooling.
- System packages are reserved for host/admin essentials, service/runtime
  dependencies, and a small system-wide convenience baseline. Interactive shell
  tooling lives in Home Manager.
- Develop-role Home Manager packages include shared interactive CLI tools such
  as `gh` so GitHub workflows are available on every develop host after the
  relevant Home Manager or NixOS switch.

## Boomer Kuwanger Emulation

`boomer-kuwanger` imports the split `modules/emulation/` module set and boots a
`kiosk` user to a tty during hardware bring-up. ES-DE with Art Book Next is
launched manually with `start-esde`; emulator launches still use the
Gamescope fullscreen wrapper, RetroAchievements-aligned RetroArch cores,
bundled shader packs, controller tooling, smoke-test tooling, dynamic display
discovery, performance-test tooling, and ScreenScraper/RetroAchievements secret
wiring. Gamescope FSR is disabled; scaling is handled by RetroArch shaders or
emulator-native internal resolution controls while preserving aspect ratio.
Controller shortcuts use Switch Pro labels: Minus is the hotkey modifier,
Minus + X opens emulator quick menus where the active launch mode
supports it, Star/Home is left as the controller turbo/local button, and
Square/Capture is used only where an emulator profile explicitly configures it.
Every `run-emulator` launch starts the lightweight per-process exit broker for
Minus + Plus twice. Xbox defaults to `xemu-hotkeys`, and PICO-8 defaults to
`pico8-hotkeys`. PS2 launches through standalone PCSX2 with managed no-wizard
configuration, launcher-side `.m3u` first-disc resolution, Vulkan 3x graphics,
resolved connected-player SDL mappings, PCSX2-native hotkey
chords, and token-backed RetroAchievements when the token secret is present.
Switch emulation uses the repo-pinned official Ryubing Canary release; refresh
`modules/emulation/ryubing-canary-pin.nix` with `scripts/update-ryubing-canary`
before rebuilding when upstream publishes a newer Canary. Boomer manages
Ryubing for Vulkan on the RX 6650M dGPU, docked fullscreen launches, 2x
internal resolution, 16x anisotropic filtering, shader/PTC cache, SDL3
controller input for every connected player using Ryubing-native stable SDL3
controller IDs, and keyboard-enabled emulator hotkeys. Before every emulator
launch, Boomer reconciles controller LEDs and writes a resolved connected-player
map that all launch-time emulator configs consume.
Switch homebrew `.nro` launchers can keep sibling `data/` assets beside the ROM;
`run-emulator` links those assets into Ryubing's emulated SD card at launch.
HDMI audio is routed through PipeWire by selecting the currently available AMD
HDMI/DP profile before ES-DE and emulator launches, with stable 48 kHz/1024
frame PipeWire buffers for emulator audio. Runtime state
lives under `/srv/emulation`;
the future 4TB ROM SSD
mounts at `/srv/emulation/roms` from the Btrfs filesystem labeled `roms`.
The OS disk uses one Btrfs filesystem labeled `nixos` mounted at `/`.

See [`docs/boomer-kuwanger-overview.md`](docs/boomer-kuwanger-overview.md) for
a one-page hardware/software map and
[`docs/boomer-kuwanger-emulation.md`](docs/boomer-kuwanger-emulation.md) for
ROM, BIOS, PICO-8, TeknoParrot, controller, shader, display, and scraper setup
notes.

## Agent Launchers

- Develop hosts expose `codex`, `gemini`, `gemini-cli`, `opencode`, and
  `agent-browser` through Nix-managed wrapper scripts.
- Retired develop-user artifacts are cleaned from one inventory in
  `home/profiles/cleanup.nix`; add old skills, hooks, and agent state there
  instead of adding scattered cleanup activation snippets.
- The shared agent instructions live at `home/config/AGENTS.md` in the repo and
  are published to each agent's native path. Codex reads `~/.codex/AGENTS.md`,
  Gemini reads `~/.gemini/GEMINI.md`, and OpenCode reads
  `~/.config/opencode/AGENTS.md`.
- WSL hosts also publish the same agent instructions to the Windows-side Codex
  Desktop path `%USERPROFILE%\.codex\AGENTS.md` so Codex Desktop sessions that
  run against the WSL guest keep the same shared instructions.
- WSL hosts keep fish as the develop login shell, but the NixOS-WSL shell
  wrapper has a narrow compatibility path: nested Bash-quoted worktree probes
  run through Bash after the normal NixOS and fish environment is imported.
- The managed `agent-browser` wrapper defaults `AGENT_BROWSER_ENGINE=chrome`
  unless you override it explicitly, so local automation stays on the
  profile-capable Chrome engine even if upstream auto-selection changes.
- `codex`, `gemini`, `gemini-cli`, and `opencode` delegate to installed
  user-local CLIs under
  `/home/nixos/.local/share/ghostship-agent-tools/npm/bin`.
- `ghostship-agent-maintenance.service` owns automatic agent upkeep. Its
  timer runs on boot and every `4h`, with `Persistent=true` so missed runs
  fire after WSL resumes, and it installs or upgrades the user-local agent
  CLIs, ensures the managed `skills` CLI is available, refreshes shared global
  skills,
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
  rewritten to `(ghostship-free)`.
- For immediate bootstrap as the logged-in user, run
  `ghostship-agent-maintenance`. The system service is still what runs on boot
  and every `4h`.
- OpenCode remains an installed interactive CLI on develop hosts, but the repo
  no longer starts a managed WSL `opencode serve` user service.
- Develop-host convergence also cleans the known stale `workmux set-window-status ...` entries from `~/.codex/hooks.json` so removed repo-managed tooling does not keep breaking Codex hooks. The cleanup preserves unrelated valid hooks, warns instead of rewriting malformed JSON, and takes effect after the relevant Home Manager or NixOS switch. Restart any already-running Codex sessions after the switch if they were holding the stale hook state open.
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

## Shared Skills

- Shared repo-managed skills live under `home/config/skills/` and are linked
  into `~/.agents/skills/` on develop hosts. Managed external `skills` CLI
  installs also land under `~/.agents/skills/`, but they are maintained by
  `ghostship-agent-maintenance` instead of the repo-owned skill tree.
- The curated shared set is `ghostship-audit-worktree`,
  `ghostship-merge-worktree`, `ghostship-pull-worktree`, and `grill-me`.
- `ghostship-audit-worktree` is the current Codex session audit workflow. It
  audits only session changes, checks for concrete issues including
  documentation and README gaps, and produces a fix plan without editing files
  unless explicitly asked.
- `ghostship-merge-worktree` is the main local worktree merge workflow to use
  after review approval. It updates `main` from `origin/main` when possible,
  merges current `main` into the worktree branch, verifies the branch, merges
  back into `main`, and pushes `main` without using the pull request path.
- `ghostship-pull-worktree` is the pull request workflow for worktrees that
  should land through GitHub. It pushes the branch, opens a draft PR, requests
  Codex review, resolves review and CI issues, and marks the PR ready only
  when the review and checks pass.
- `grill-me` is vendored from Matt Pocock's MIT-licensed skills repo for
  plan and design stress-testing.

## Self-Hosted Stack

The container stack lives in the flat
[`modules/self-hosted/default.nix`](/home/nixos/nixos-config/modules/self-hosted/default.nix)
inventory. Services use Podman, native healthchecks, and registry auto-update.
Only Plex exposes host ports; every other service is intended to stay on
internal networking and be reached through the reverse-proxy/tunnel path.

Key services include Plex, Homepage, Muximux, the `arr` stack,
qBittorrent/VueTorrent, SearXNG, RomM, Grimmory, Chaptarr, BookStack,
PyLoad, RSS-Bridge, PriceBuddy, Codex, Agent Zero, and n8n.

Codex runs at `https://codex.ghostship.io` as a Nix-based Podman container
with Docker-in-Docker enabled for app-server workflows. Its Codex home, nested
Docker state, and `/nix` store are persisted under `/srv/apps/codex` and named
Podman volumes. The container seeds Codexapp's custom provider through a local
OpenAI-compatible mux backed by the managed Ollama Cloud and OpenCode Go
secrets. The dedicated `codex-auto-update.timer` rebuilds the local runtime
image and restarts the service so `codexapp` and `@openai/codex` refresh while
persistent state survives upgrades.

Retired `chill-penguin` self-hosted service artifacts are cleaned from the
allowlist in
[`modules/self-hosted/cleanup.nix`](/home/nixos/nixos-config/modules/self-hosted/cleanup.nix).
Add old `/srv/apps` paths, Podman containers/images, systemd units, and
dashboard rows there instead of scattering one-off cleanup snippets through
service modules.

PyLoad has a daily `04:00` `pyload-restart-failed` timer that checks the
internal `http://pyload:8000` API and restarts failed queue links when present.

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
name after the VPN namespace changes. The managed qBittorrent queue allows 5
active downloads and 20 active torrents, with the global download cap set to
20 MB/s, slow torrents excluded from active queue limits, and qBittorrent's
post-completion recheck enabled. Torrent data is rooted at
`/downloads/Torrent`, with incomplete torrent data under
`/downloads/Torrent/.incomplete`, so the shared `/downloads` mount root stays
clear of qBittorrent partfiles. A `vuetorrent-auto-resume` timer retries
errored qBittorrent torrents every 5 minutes through qBittorrent's internal
Web API start action without a per-torrent retry cap. NZBGet shares Gluetun's
VPN namespace and internal callers should reach it at `http://gluetun:5001`.
Gluetun secret bundle must provide PIA credentials (`PIA_USER`/`PIA_PASS` or
legacy `OPENVPN_*` names) and `HTTP_CONTROL_SERVER_API_KEY`, and does not
require any application-specific benchmark credentials.

n8n runs as a single SQLite-backed workflow orchestrator in this repo and is
intended to stay behind Cloudflare for browser access. The live Muximux entry
still needs a manual reorder on `chill-penguin` after deployment so it sits
directly under Bazarr.

Chaptarr now extends the arr stack to books and audiobooks. It should mount the shared downloads root at `/downloads`, manage `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` as separate library roots, and stay visible in Homepage plus the Muximux dropdown immediately before Bazarr. Grimmory is still the primary reading and listening surface, so it also mounts both library roots. Public `chaptarr.ghostship.io` exposure remains part of the external Cloudflare/tunnel workflow rather than repo-managed ingress.

BookStack now adds a repo-managed wiki service on `chill-penguin` with app
state under `/srv/apps/bookstack`, MariaDB state under
`/srv/apps/bookstack-db`, and Homepage visibility in the `Services` group and
a Muximux tile after Prowlarr. Keep `BOOKSTACK_APP_URL` pointed at the external
`https://bookstack.ghostship.io` origin, and treat the initial in-app setup
plus API token creation (`Authorization: Token <token_id>:<token_secret>`) as
manual post-deploy operator steps instead of repo-managed bootstrap. Public
`bookstack.ghostship.io` exposure remains part of the external
Cloudflare/tunnel workflow rather than repo-managed ingress.

CloakBrowser runs again as a standalone manager on `chill-penguin` for direct
profile management, alongside the embedded browser contract used by
repo-managed scraping images. The manager stays on the internal
`ghostship_net` network and does not use Gluetun. `pricebuddy-scraper` and
`changedetection` still launch local CloakBrowser Playwright sessions inside
their own images with `humanize=True`.

RomM currently runs cleanly on the upstream `rommapp/romm:latest` image
without the old post-start bundle rewrite. Validate future iframe regressions
against a live unpatched container before reintroducing any frontend patch.
The live NAS ROM library is mounted into RomM from
`/mnt/share/Library/ROMS/ROMS`; the service creates the sibling `.romm` assets
directory before Podman starts.
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

SearXNG is intended to run as an internal-only search hub on `ghostship_net`;
internal consumers should use the container-network address
`http://searxng:8080`. The managed `podman-searxng` `preStart` path now renders
the full `settings.yml` plus `limiter.toml`, requires the projected
`SEARXNG_SECRET_KEY` instead of generating one on the fly, and keeps a
persistent cache at `/srv/apps/searxng-cache` mounted to `/var/cache/searxng`
so cache-backed engines like Startpage retain useful state across restarts. The
active internal engine surface is performance-first: the promoted web pool is
`startpage`, `qwant`, `presearch`, `wikipedia`, and `wikidata`; the technical
pool is `arch linux wiki`, `nixos wiki`, `askubuntu`, `stackoverflow`,
`superuser`, `mankier`, `mdn`, `github`, `gitlab`, `gitea.com`, `sourcehut`,
`huggingface`, `repology`, `pypi`, `npm`, `crates.io`, `pkg.go.dev`,
`packagist`, `pub.dev`, `rubygems`, `hex`, and `lib.rs`; the research pool is
`openalex`, `semantic scholar`, `pubmed`, `arxiv`, and `crossref`; and the news
pool is `reuters`, `tagesschau`, and `wikinews`. Internal callers should use
explicit `/search?q=...&format=json&engines=...` pools instead of relying on the
full active engine list. The latest lightweight direct probes promoted
`presearch`, while `brave` and `karmasearch` stayed out of the default web pool
after immediate `429` and `403` responses respectively.

PriceBuddy seeds a `pricebuddy@ghostship.io` / `pricebuddy` login and reads a
persistent agent API token from the `pricebuddy` source projection. The live
`/srv/apps/pricebuddy/pricebuddy-agent.env` file contains a shell-safe
`PRICEBUDDY_API_TOKEN="id|token"` bearer line for direct API use. The host
token-sync now strips any previously persisted token ID before rewriting that
file, and the managed `podman-pricebuddy` post-start path verifies the app env
files, scraper reachability, and final bearer-token shape without treating
upstream auth-route bugs or third-party Cloudflare challenges as Ghostship env
regressions.


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
- `secrets/files/sources/**/*.age` stores source/provider/service encrypted env
  files consumed by NixOS through `ragenix`. Services receive stable runtime env
  files projected under `/run/ghostship-secrets`.

Helper commands:

```bash
secret-edit-keygen         # create ~/.ssh/id_ed25519_ragenix if missing
secrets-list-keys          # list logical-unit catalog keys
secret-list                # inspect catalog entries and recipient groups
secret-edit <logical-id>   # edit one logical-unit .age file directly
secret-rekey               # rekey all .age files after recipient changes
```

Normal operator flow is direct source-bundle editing with `secret-edit
<logical-id>`. Use `secrets-list-keys` or `secret-list` to find the provider or
service source you need, then run `secret-rekey` only when recipient membership
changes.

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
  `/mnt/z`. Windows PATH import is enabled for desktop interop, and explicit
  WSL FHS shims provide the small set of hardcoded `/bin/...` and
  `/usr/bin/...` paths required by Windows-side tools. Keep `/usr/bin` writable
  so Docker Desktop can manage `/usr/bin/docker-credential-desktop.exe`
  itself; add future hardcoded FHS needs to `ghostship.wsl.fhsShims` instead of
  reintroducing `envfs`.
  WSL activation stops the `/mnt/z` automount and unmounts any live NFS mount
  before reloading the generated mount units so host switches do not fail on
  stale `/mnt/z` mount state.
- WSL hosts cap `nix.settings.max-jobs` at `8` so concurrent flake shells,
  agent sessions, and host builds do not wedge `nix-daemon` under `auto`
  parallelism.
- WSL hosts also cap `nix.settings.cores` at `4` so each build job cannot
  fan out across all reported host threads and recreate the same memory-pressure
  stalls from inside a smaller job queue.
- When a WSL change alters FHS shim entries, a full WSL distro restart may be
  needed after `nixos-rebuild switch` before refreshed `/bin/...` or
  `/usr/bin/...` paths appear in the live instance.
- Login sessions raise the soft `nofile` limit to `65536` to keep busy shells,
  editors, and agent workflows from running into a low default descriptor cap.
