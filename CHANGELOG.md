# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- fix(self-hosted): seed Gluetun PIA WireGuard selection from live chill-penguin benchmarks, rank matched endpoint pairs instead of `meta[0]`/`wg[0]`, and keep boot-time selection constrained to the benchmarked regions and servers with safe fallbacks

- fix(self-hosted): use Gluetun's native container healthcheck, make Gluetun namespace dependents follow service restarts with `PartOf`/`Requires`, and switch VueTorrent to a local WebUI health probe instead of external `google.com`

### Changed
- **PyLoad health checks**: Switched the `pyload-ng` container health probe
  from `GET /api` to `GET /favicon.ico` because the current upstream image now
  returns `401 UNAUTHORIZED` on `/api`, which left Podman health checks
  permanently failing and blocked clean NixOS activation.
- **agent-browser bootstrap**: Stopped passing `--with-deps` during develop-host `agent-browser` runtime bootstrap; the Nix wrapper already supplies the needed shared libraries, so maintenance now treats those system dependencies as already packaged instead of attempting unsupported distro package-manager bootstrapping.
- **Codex skill-creator override**: Renamed the shared vendored
  `skills-creator` entry back to `skill-creator`, refreshed the repo-managed
  copy from `vercel-labs/agent-browser` `v0.9.3`, and now reassert the Codex
  built-in `~/.codex/skills/.system/skill-creator` path as a managed symlink to
  `~/.agents/skills/skill-creator` during develop-profile activation and
  `ghostship-agent-maintenance`.
- **Hermes shared skill seeds**: Added a repo-managed Hermes shared
  `skill-creator` seed under
  `modules/self-hosted/hermes-seeds/shared/skills/skill-creator/`, imported the
  upstream `vercel-labs/agent-browser` `v0.9.3` package as the baseline, and
  adapted the Hermes copy with minimal `SKILL.md` changes plus Hermes-aware
  init/validation scripts. `podman-hermes` now seeds that shared skill into
  `/srv/apps/hermes/home/seeds/shared/skills/skill-creator/` only when the
  runtime-owned directory is missing.
- **Gluetun PIA WireGuard selector**: Migrated `chill-penguin` Gluetun from native PIA OpenVPN to Gluetun's custom-provider WireGuard path, added a daily PF-capable PIA server selector that caches the preferred winner under `/srv/apps/gluetun/pia-wireguard-selection.json`, regenerated the runtime env at Gluetun startup, kept PIA VPN-side port forwarding on the persisted `/srv/apps/gluetun` state mount, and updated the monitor to use Gluetun's generic `/v1/portforward` control route while still reconciling qBittorrent/VueTorrent after startup and reconnects.
- **Hermes profile SOUL seeds**: Added tracked Hermes persona source files for
  the `assistant`, `operations`, and `supervisor` gateways under
  `modules/self-hosted/hermes-seeds/`, and `podman-hermes` now seeds each
  profile `SOUL.md` into `/srv/apps/hermes/home/seeds/profiles/<profile>/`
  only when that file is missing so existing runtime variants are preserved.
- **Chaptarr book stack**: Added a repo-managed Chaptarr service to the `chill-penguin` arr stack with persisted config, shared `/downloads` access for both torrent and usenet flows, Homepage visibility, and declarative Muximux placement after Bazarr and before `n8n`. Grimmory now mounts both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` so it remains the first-class consumption surface for the shared library roots, while the public `chaptarr.ghostship.io` route stays part of the external Cloudflare/tunnel workflow.
- **Develop GitHub CLI baseline**: Added `gh` to the shared develop Home
  Manager package set so every develop-profile host gets the GitHub CLI by
  default.
- **Bootstrap WSL hostname handling**: `bootstrap.sh` is now tracked as an
  executable script and falls back from `hostnamectl` to `hostname`, avoiding
  the unsupported WSL2 systemd-hostname failure while still changing the live
  hostname during bootstrap. It now also requires an explicit hostname argument
  and requires being run through `sudo`. It emits the matching
  `nixos-rebuild switch --flake .#<hostname>` command and a `nix-shell -p git`
  hint alongside the bootstrap JSON. Durable hostname persistence remains
  declarative.
- **Develop agent maintenance**: Replaced the launch-time `npx` preflight flow
  for `codex`, `gemini`, and `opencode` with installed user-local agent CLIs
  under `/home/nixos/.local/share/ghostship-agent-tools/npm`, added a
  boot-triggered plus 4-hour persistent `ghostship-agent-maintenance` systemd
  timer to upgrade those CLIs and refresh shared skills, Gemini extensions,
  `agent-browser`, and OpenCode's free OpenRouter config, and simplified the
  launchers down to approval-default injection plus direct exec of the
  installed binaries.
- **WSL Nix build fanout**: WSL hosts now cap `nix.settings.cores` at `4` so
  each daemon-dispatched build job cannot claim all reported CPU threads and
  recreate the same memory-pressure stalls inside an `8`-job queue.
- **Login descriptor headroom**: Added a shared soft `nofile` login limit of
  `65536` so shell-heavy local workflows have more file descriptor headroom
  before hitting per-session limits.
- **Global `rg` availability**: Added `ripgrep` to the shared
  `environment.systemPackages` baseline so server-role hosts such as
  `chill-penguin` have `rg` available out of the box.
- **CloakBrowser managed profile set**: Replaced the old default `Direct`
  and `VPN` manager profiles with repo-managed `assistant`, `operations`,
  `supervisor`, and `Changedetection` profiles, and added a host-managed
  keepalive so the `Changedetection` profile is relaunched automatically when
  the manager stays healthy but that profile stops.
- **n8n orchestration stack**: Added a single SQLite-backed `n8n` service for `chill-penguin`, exposed it to Hermes over `ghostship_net`, documented the dedicated `N8N_API_KEY` handoff through `hermes-secrets`, added Homepage visibility, and declared the Muximux dropdown placement immediately after Bazarr with a documented one-time live reorder step on the host.
- **OpenSpec worktree handoff**: The develop-host `openspec` wrapper now keeps
  proposal/design/tasks work on `main`, moves worktree creation or reuse to
  `apply` with the `.worktrees/<name>/` path, and treats `archive` as the step
  that reconciles any matching change worktree back into `main`, commits the
  archive move, and removes the worktree.
- **WSL Nix daemon concurrency**: WSL hosts now cap `nix.settings.max-jobs`
  at `8` instead of inheriting `auto`, which was resolving to `22` on
  `launch-octopus` and letting concurrent flake shells, agent sessions, and
  host builds push `nix-daemon` into multi-gigabyte memory spikes and socket
  stalls.
- **Personal OpenSpec workflow**: Develop hosts now reapply append-only
  Ghostship propose/apply/archive snippets after both `openspec init` and
  `openspec update` so upstream workflow files stay intact while
  main-first planning, root-cause-first debugging, and
  worktree-reconcile-before-archive guidance
  survive refreshes without extra OpenSpec config files.
- **RomM proxy base-path fix**: Muximux's same-origin `/romm/` proxy now
  injects a real document `<base href="/romm/">` for RomM before the app
  boots, which keeps current and future bundles on the correct router base
  even when they ship an empty Vite env object instead of a rewritable
  `BASE_URL` literal. The proxy also now handles RomM's leaked
  `/ws/socket.io/` root websocket path instead of returning a Muximux-side
  `404`.
- **Hermes whole-home runtime**: Updated Hermes to follow the upstream whole-home image contract by mounting `/srv/apps/hermes/home` at `/home/hermes`, `/srv/apps/hermes/workspace` at `/workspace`, and a seeded host path `/srv/apps/hermes/nix` at `/nix` so the bundled Nix store survives container replacement without being hidden behind an empty mount.
- **Hermes `/nix` reseed guard**: Hermes startup now compares the persisted `/srv/apps/hermes/nix` store with the current `ghostship-hermes:latest` system closure and refreshes the mount when that closure is missing, preventing stale `/nix` data from masking the image's bootable store after upstream image updates.
- **Muximux service placement**: Removed Honcho from the generated Muximux tile
  list, moved PriceBuddy back into the Muximux dropdown directly after Bazarr,
  and keep the generated dashboard layout aligned with the retired Honcho
  stack.
- **Honcho retirement**: Removed the Honcho self-hosted stack, dropped Hermes'
  `HONCHO_*` integration wiring and shared Honcho compatibility-state
  management, removed Homepage Honcho entries, and removed the stale
  `litellm-secrets` declaration now that the service is retired.
- **Homepage stale-entry pruning**: Homepage activation now explicitly deletes
  stale `Honcho`, `Honcho Redis`, and `Honcho DB` entries from `services.yaml`
  after `ghostship-config set` so retired services do not linger in the live UI.
- **PriceBuddy token verification**: Normalized the managed
  `pricebuddy-agent.env` bearer rewrite so repeated post-start runs preserve a
  single `id|token` pair, and added host-managed post-start checks for the app
  env files, scraper reachability, and final token format without conflating
  known upstream auth-route or Cloudflare target issues with Ghostship runtime
  wiring.
- **OpenCode programming free-model refresh**: The develop-host `opencode`
  wrapper now refreshes a generated OpenCode config once per UTC day from
  OpenRouter's ranked programming free-model frontend endpoint, stores that
  generated config under the user's state directory, exports `OPENCODE_CONFIG`
  to it at launch, sources the free programming models from that endpoint, and
  rewrites the generated OpenCode model display labels from `(free)` to
  `(ghostship-free)`. The static OpenRouter model maps were removed from both
  Nix-managed OpenCode config paths, which now only retain the explicit
  `permission = "allow"` default.
- **Develop auth cache policy**: Moved the managed `ssh-agent` setup into the
  develop Home Manager profile, switched it to a fixed `/run/user/1000/ssh-agent`
  socket with a `12h` key lifetime, removed the brittle WSL-only post-start
  parser that could leave the user service failed, and made develop-host
  `sudo` credential caching global with a `12h` timeout so fresh agent PTYs do
  not constantly re-prompt while server-only hosts keep the stricter default
  scope.
- **Hermes native image entrypoint**: Removed the repo-side Hermes startup
  shim, entrypoint override, command override, and separate `.honcho` bind
  mount so `chill-penguin` follows the image's native
  `/usr/local/bin/ghostship-hermes-runtime entrypoint` contract while the
  current workstation layout owns the persisted `/opt/data`, `/workspace`, and
  `/nix` mounts.
- **Develop agent launcher defaults**: Develop-host `codex`, `gemini`, and
  `opencode` now declare explicit YOLO or allow-all execution defaults instead
  of relying on mixed upstream behavior; Gemini now applies YOLO through its
  wrapper because upstream `settings.json` no longer accepts that mode.
- **Muximux RomM embedding**: Switched Muximux's RomM tile to a same-origin
  `/romm/` reverse proxy and now install a managed Muximux nginx vhost that
  proxies RomM by service name on `ghostship_net`, because the public
  `romm.ghostship.io` hostname is Cloudflare Access-protected and not a stable
  iframe target.
- **RomM startup hook removal**: Removed the stale `podman-romm` post-start
  bundle rewrite after validating that the upstream RomM `4.8.0` image starts
  cleanly without it; the failing patch target was the source of the live
  startup wedge.
- **RomM iframe shim**: Muximux now injects an iframe-only RomM runtime shim
  ahead of RomM's main module entry instead of rewriting the served RomM bundle
  on disk, and the shim cache-bust is owned by the Muximux config so Chrome can
  be forced onto corrected injection changes without touching RomM assets.
- **OpenSpec init defaults**: The develop-host `openspec` wrapper now injects
  `--tools codex,gemini,opencode --profile core` for `openspec init` unless
  the caller passes explicit `--tools` or `--profile` flags.
- **Shell flake timeouts**: Increased Starship's prompt scan timeout and
  direnv's warning timeout to 30 seconds so slow `use flake` environments have
  more time to initialize before the prompt or warning path gives up.

## [0.1.9] - 2026-04-02

### Removed
- **LiteLLM stack**: Removed LiteLLM and its dedicated Postgres container from the self-hosted stack for now, along with Homepage and Muximux entries and the active `litellm-secrets` declaration. Encrypted secret material in `secrets.yaml` is left untouched until it is intentionally cleaned up.

### Changed
- **Agent memory rewrite**: Rewrote the repo `AGENTS.md` into a shorter
  operating-memory format so it keeps durable repo facts without turning into a
  running debug log, and aligned the shared `home/config/AGENTS.md` preference
  layer with the newer commit/verification/documentation workflow.
- **Shared skill rename**: Renamed the vendored shared `skill-creator` skill to
  `skills-creator` locally while keeping it pinned to the upstream
  `vercel-labs/agent-browser` `skill-creator` package.
- **Python skill defaults**: Updated the shared Python skill to require `src/`
  layout, `uv`, `ruff`, `pytest`, and `basedpyright`, with `ruff format .`,
  `ruff check .`, full-project `pytest`, and full type coverage as the default
  workflow.
- **SSH interaction guidance**: Tightened the shared SSH skill around
  non-blocking tmux-driven remote workflows so prompt-driven commands are
  started in detached tmux sessions and advanced through `capture-pane` plus
  `send-keys`.
- **WSL path guidance**: Updated the shared WSL skill to prefer `/mnt/c/...`
  for Windows files, added `wslpath` conversion guidance, and refreshed the
  PowerShell reference with tested non-interactive patterns for this host,
  including the requirement to use a Windows path with
  `powershell.exe -File`.
- **OpenSpec agent workflow**: Replaced the old Superpowers-based CLI workflow with repo-local OpenSpec scaffolding for Codex/Gemini/OpenCode, exposed an `openspec` CLI wrapper in the shared develop toolchain, and migrated active planning references from `docs/superpowers` to the repo-root `openspec/` tree.
- **Legacy Superpowers cleanup**: Develop-profile activation now removes the old `~/.agents/skills/superpowers`, `~/.gemini/extensions/superpowers`, and `~/.config/opencode/plugins/superpowers` checkouts and prunes Gemini's stale enablement record during activation.
- **Agent launcher preflight**: Standardized the develop-host `codex`, `gemini`, and `opencode` wrappers around a shared `npx` launch flow that refreshes global `skills`, refreshes OpenSpec instructions when launched inside an OpenSpec repo, warns instead of aborting on preflight failures, and keeps Gemini extension updates behind the same warning-only contract.
- **Shared skill curation**: Reduced the repo-managed shared skill inventory to `nix`, `python`, `ssh`, `wsl2`, and the vendored shared `skills-creator` package, removed the local `agent-browser`, `build123d`, and `dispatching-cli-subagents` skills, and rewrote the retained local skills into a leaner modular format aligned with current skills.sh guidance.
- **Flake repo shell**: Added a default Linux `devShell` to the root flake so `.envrc` `use flake`, `direnv`, and `nix develop` all work in the local development environments without changing any host outputs.
- **agent-browser local runtime**: Wrapped the develop-host `agent-browser` command with a Nix-managed browser `LD_LIBRARY_PATH` so Puppeteer's downloaded Chrome can launch on NixOS/WSL instead of failing on missing GTK/NSS/X11/GBM shared libraries.
- **SearXNG direct-network max-open tuning**: Moved SearXNG off the Gluetun network namespace onto `ghostship_net`, switched Hermes to the internal `http://searxng:8080` address, restored the container's default internal port `8080`, replaced the implicit default-engine inheritance with a Nix-managed allowlist plus category/weight overrides, moved SearXNG config generation into `podman-searxng` `preStart` so engine changes restart cleanly, and pruned repeatedly blocked or unstable engines such as Brave, Qwant, Kickass, SolidTorrents, PodcastIndex, Geizhals, Tootfinder, and Semantic Scholar from the live search surface.
- **SearXNG live tuning follow-up**: Re-ran the public Access-protected SearXNG instance through iterative API and browser probes, removed engines that still failed or degraded quality off VPN (`annas archive`, `mojeek news`, `qwant*`, plain `duckduckgo`, and the full Brave family), kept stronger contributors like `mojeek`, `google`, `duckduckgo news/images/videos`, `reuters`, `youtube`, `sepiasearch`, and `bt4g`, and added a Google fallback into the `it` category so agent-style infrastructure queries no longer return empty result sets.
- **SearXNG Brave reinstatement**: Re-enabled `brave`, `brave.news`, `brave.images`, and `brave.videos` in the curated engine allowlist because the active search policy now explicitly favors Brave's independent index coverage over the operational cleanliness gained by pruning its rate-limited engine family.
- **SearXNG autocomplete**: Switched the instance autocomplete backend from `duckduckgo` to `bing` after live benchmarking showed Bing suggestions were faster and more complete for agent-style queries than DuckDuckGo, Startpage, Wikipedia, Mwmbl, or Brave.
- **SearXNG category tuning**: Rebalanced the curated engine set around the current agentic-search priorities by enabling Bing web search, Repology package search, Apple Maps, Google Play Apps, Erowid, Moviepilot, and additional icon engines, removing `hoogle` and `gentoo`, promoting Reuters/Google News/YouTube/Wikipedia in their respective categories, and narrowing package, software-wiki, app, movie, and icon engines to the categories where they provide the strongest signal.
- **SearXNG category tuning follow-up**: Dropped `svgrepo` again after live icon probes immediately hit rate limits, and raised per-engine timeouts on the slower app, package, icon, and Erowid sources so the engines explicitly kept for those categories have a chance to contribute before the global request cutoff.
- **SearXNG package and other cleanup**: Removed `duckduckgo weather` after repeated live `400` errors on non-weather queries, pushed package search harder toward `pypi`, `repology`, and Alpine, and demoted the long tail of ecosystem-specific package registries into `it` so package-name lookups are less dominated by unrelated exact-name matches.
- **SearXNG PyPI engine override**: Replaced the upstream PyPI HTML scraper with a local exact-match engine mounted into the container that uses PyPI's JSON API, and marked curated engines `inactive = false` so default-off engines like `repology` can be activated reliably from the repo-managed engine list.
- **SearXNG weather source swap**: Replaced `openmeteo` with `wttr.in` in the curated weather category after live tests showed the old weather path returning no useful answers while wttr's upstream JSON endpoint remained healthy.
- **Global Bash defaults**: Moved Bash completion and baseline readline/history behavior into the shared NixOS layer so all Bash shells, including root, now get `bash-completion`, case-insensitive ambiguous completion, cleaner history handling, incremental history writes, and `checkwinsize` by default.
- **CloakBrowser healthcheck**: Replaced the `wget --spider` Podman probe with a Python `urllib` GET against the local manager endpoint, because the current image on `chill-penguin` serves the app correctly but still reports repeated false-negative healthcheck failures under the `wget` runner.
- **Host role refactor**: Added explicit `ghostship.host.roles` booleans, split WSL into its own top-level module area, and moved Home Manager into `base`, `server`, `develop`, and `wsl` profile layers. Server-role hosts now default to `bash`, develop-role hosts default to `fish`, and the package split is cleaner between system packages and user packages.
- **Flake host construction**: Consolidated repeated `nixosSystem` wiring behind a shared `mkHost` helper and removed the unused `nixpkgs-unstable` input.
- **Self-hosted inventory consistency**: Reordered the flat self-hosted module inventory into documented category blocks and removed the last non-Plex host port exposure by keeping CloakBrowser on internal networking with the standard Podman healthcheck cadence.
- **Workflow docs**: Rewrote the local workflow guidance to match the actual repo workflow instead of the old `plan.md`-driven process.
- **Docker Hub auth support**: Added a `dockerhub-secrets` bundle and runtime auth-file generation so the self-hosted Podman stack can authenticate Docker Hub pulls instead of hitting rate limits during restart-time updates.
- **Docker Hub placeholder fallback**: The Docker Hub auth hook now writes an empty `auths` file when the secret bundle still contains the placeholder values, so public pulls can continue anonymously instead of failing the whole stack during deploy.
- **Podman auto-update**: Every self-hosted OCI container now sets `pull = "always";` and carries Podman's registry auto-update label, and a daily native `podman auto-update` timer refreshes changed images in place. Failed restarts are still surfaced through systemd/journal for now.
- **WSL `/mnt/z` NFS mount**: Replaced the WSL-only `Z:`-backed SMB mount script with a direct Synology NFS automount at `/mnt/z`, reusing the tuned `chill-penguin` mount options so access is faster on-network and fails gracefully when the NAS is unavailable or the host is off-network.
- **PyLoad healthcheck**: Switched the PyLoad container health probe from `/` to `/api`, because the current web UI config can leave the root path in an internal redirect loop even while the service itself is healthy.
- **LiteLLM database startup**: LiteLLM now writes a runtime env file that maps the existing secret bundle onto the `DATABASE_URL` variable the upstream image actually uses, and the Postgres side now writes a real `POSTGRES_PASSWORD` runtime env file instead of passing the literal `env:LITELLM_DB_PASS` marker through to the container. The LiteLLM Postgres unit also reconciles the `litellm` role password from secrets on startup so older initialized volumes converge to the current secret. This allows Prisma migrations to run and fixes the LiteLLM UI's `Not connected to DB!` login failure on `chill-penguin`.
- **LiteLLM ChatGPT subscription wiring**: LiteLLM now mounts a persistent ChatGPT OAuth token directory and ships a proxy config for the current `chatgpt/` provider models (`gpt-5.4`, `gpt-5.4-pro`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.3-instant`, and `gpt-5.3-chat-latest`) so ChatGPT-subscription-backed models can be added without API keys and keep their OAuth session across container restarts.
- **Native Nix docs**: Updated the repo documentation and agent instructions to use native `nix`, `nixos-rebuild`, and `switch-to-configuration` commands instead of `nh`.
- **CloakBrowser native origin patch**: Replaced the custom aiohttp proxy with a startup patch against the upstream manager's `AuthMiddleware`, so the app now strips incoming `Origin` headers at the ASGI boundary and keeps the native VNC/CDP WebSocket handling intact.
- **PyLoad config application**: `ghostship-config` now recognizes `pyload.cfg` as PyLoad's typed config format and updates the existing section/key lines in place, so the PyLoad activation settings actually take effect instead of being appended as invalid `section.key=value` lines.
- **PyLoad NFS startup**: Restored the LinuxServer image's supported root-run startup mode and replaced the broken `fix-attrs/down` override with a narrow patch to `init-pyload-config/run` that keeps `/config` ownership handling but skips the `/downloads` `chown` on the NFS share.
- **Documentation Migration**: Merged `GEMINI.md` into `AGENTS.md` and removed devenv references from `README.md`. Added self-hosted services overview.
- **ghostship-config YAML Upserts**: Fixed Homepage-style list-group creation in `ghostship-config.py` so paths like `[Utilities].[OmniTools].icon` create missing groups with the correct list container and pass the script self-tests again.
- **Homepage resources widget typing**: The Homepage activation script now writes the resources widget's `cpu`, `memory`, and `network` options as native YAML booleans instead of quoted strings, which restores the network bandwidth section instead of showing `API Error`.
- **Homepage network stats mount**: Homepage now keeps the resources widget pinned to `end0` on `chill-penguin` and mounts only the network-related sysfs paths needed to resolve `end0`'s host symlink target, avoiding the broken `/sys/class/net` links without exposing the wider `/sys` tree that made Homepage's disk probe fail.
- **RomM iframe startup hook**: Added a `podman-romm` `postStart` hook that patches RomM's routed iframe crash trigger in the active hashed frontend bundle and cleans up temporary debug assets created during live investigation.
- **VueTorrent LSIO integration**: Replaced the hand-managed VueTorrent zip extraction with the official `ghcr.io/vuetorrent/vuetorrent-lsio-mod` on the LinuxServer qBittorrent image. The service no longer forces `-u 3000:3000`, the stale manual `/srv/apps/vuetorrent/ui` state is removed during activation, and qBittorrent is configured to use `/vuetorrent`, avoiding the recurring `Unacceptable file type, only regular file is allowed.` failure.
- **Gluetun PIA compatibility**: The `podman-gluetun` `preStart` hook now mirrors legacy `OPENVPN_PASS` into `OPENVPN_PASSWORD` before writing `/run/secrets/gluetun-runtime.env`, keeping the current Gluetun image compatible with the existing secret bundle on `chill-penguin`.

### Added
- **SSH workflow references**: Added shared SSH skill references for common
  tmux background patterns and interactive SSH command patterns.
- **Honcho stack**: Added a local Honcho stack for Hermes using one s6-supervised app container plus database and Redis sidecars, wired Hermes to generate `~/.honcho/config.json` at startup, and added Homepage and Muximux entries.
- **RSS-Bridge and PriceBuddy**: Added internal-only RSS-Bridge and PriceBuddy services to the Ghostship stack, wired both into Homepage's Services column, added the PriceBuddy MySQL/scraper sidecars, and sourced the persistent PriceBuddy agent API token from the `pricebuddy-secrets` bundle.
- **PriceBuddy env bootstrap**: Moved PriceBuddy env-file generation into the service start path so the MySQL and app containers can see `/srv/apps/pricebuddy/{pricebuddy.env,pricebuddy-db.env,pricebuddy-agent.env}` reliably after secrets are installed.
- **PriceBuddy bearer format**: The persisted agent token now writes a shell-safe `PRICEBUDDY_API_TOKEN="id|token"` bearer line into `/srv/apps/pricebuddy/pricebuddy-agent.env` so non-interactive API calls authenticate correctly.
- **PriceBuddy process env**: Restored PriceBuddy's app `environmentFiles` so the upstream `start-app.sh` sees the DB host and credentials it waits on before Apache starts.
- **Nix command reference**: Added a native Nix command reference under the Nix skill with build-first, no-`sudo`, and `chill-penguin-root` deployment guidance.
- **Hermes service**: Added a new `ghcr.io/ghostship-io/ghostship-hermes:latest` self-hosted service with Homepage and Muximux entries, internal service URL wiring for the existing stack, RomM/Grimmory secret imports for `*_USER` / `*_PASS`, and a named Podman volume for `/nix` so the image keeps its bundled entrypoint store.
- **ghostship-config Utility**: A self-verifying, idempotent configuration manager for surgical updates to XML, YAML, INI, and KV files. Supports secure secret injection via environment/file references.
- **Pure Surgical Migration**: Migrated all self-hosted services (Sonarr, Radarr, Plex, Homepage, etc.) to a pure surgical configuration model, removing all full-file templates and enforcing the "Ghostship Standard" for identity and privacy.
- **Unified Agent Tooling**: Added a shared `~/.agents`-based skill/instructions model and a Gemini delegation MCP server for repo research and plan generation across Gemini, OpenCode, and Codex.

## [0.1.8] - 2026-03-20

### Removed
- **Agent Browser Skill**: Removed the `agent-browser` Gemini skill definition. The `agent-browser-mcp` server remains active for tool-based browser automation.

## [0.1.7] - 2026-03-19

### Added
- **SSH Skill**: Created a new Gemini skill for advanced remote server management based on `mcp-ssh-manager`.
- **Agent Browser Skill**: Created a new Gemini skill for token-efficient browser automation via `agent-browser-mcp`.

### Changed
- **SSH MCP**: Swapped `@aiondadotcom/mcp-ssh` for `mcp-ssh-manager` by `bvisible` for enhanced remote management capabilities.
- **Browser Automation**: Swapped `browser-use` for `agent-browser-mcp` to leverage token-efficient accessibility trees and semantic locators.

## [0.1.6] - 2026-03-18

### Changed
- **Gemini Template**: Overhauled `home/config/gemini.md` to follow 2026 Open Source Software (OSS) best practices.
- **Workflow**: Updated Conductor `workflow.md` to prioritize autonomous verification and report results.
- **Policies**: 
    - Established "Open Source Excellence" as a baseline for all projects.
    - Added "Continuous Learning" as a HIGH PRIORITY directive to record mistakes and new discoveries in project memory.
    - Prohibited `save_memory` in favor of centrally managed cross-project memory via user prompts.
    - Prioritized `nh` for all supported system operations.
    - Updated TDD policy to prioritize unit/integration tests for applications and test environments for infra/config.

## [0.1.5] - 2026-03-11

### Added
- **Python Skill**: Added a new Gemini skill for modern Python development using `uv`, Nix flakes, `black`, `isort`, and `pyright`/`pylance`.

## [0.1.4] - 2026-03-11

### Added
- **SSH MCP**: Added `mcp-ssh` for remote task execution via `@aiondadotcom/mcp-ssh`.
- **Browser Automation**: Switched from `playwright` to `browser-use` MCP using `mcp-browser-use`.
- **Gemini Extension**: Installed `richardcb/oh-my-gemini` for advanced workflow orchestration.
- **System Packages**: Added `uv` to common system packages for MCP runners.

## [0.1.3] - 2026-03-11

### Changed
- **Gemini Config**: Enabled the experimental `plan` mode in `modules/develop/gemini.nix`.

## [0.1.2] - 2026-03-10

### Added
- **Host Bootstrap Script**: Implemented `bootstrap.sh` for initial host setup, age key generation, and hardware configuration capture.
- **Host Registration**: Added `register-host` CLI tool to automatically integrate new hosts (updating `.sops.yaml`, creating host directories, and re-encrypting secrets).
- **Documentation**: Added comprehensive "Bootstrap a New Host" section to `README.md`.

## [0.1.1] - 2026-03-09

### Added
- **System Skill Update**: Added `nh os build` to the Command Reference Matrix for testing NixOS configurations.

## [0.1.0] - 2026-03-09

### Added
- **Automated Maintenance**: Configured automated daily Nix garbage collection and system generation pruning (keeping 7 days) in `modules/common/default.nix`.
- **Maintenance Documentation**: Added a "Maintenance & Cleanup" section to `README.md` with instructions for `nh clean`.
- **System Skill Update**: Reinforced the "Documentation Mandate" and added "Versioning & Conductor" autoincrement logic in `home/config/skills/system.md`.
- **Version Tracking**: Created the `VERSION` file and initialized it at `0.1.0`.
- **Initial Changelog**: Created `CHANGELOG.md` to track project evolution.

### Changed
- **Config Apply Workflow**: Updated documentation to prefer `nh os switch` over `nixos-rebuild`.
- **Memory Policy**: Updated `AGENTS.md` to track the new maintenance automation.
