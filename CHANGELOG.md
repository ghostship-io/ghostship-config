# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Removed
- **LiteLLM stack**: Removed LiteLLM and its dedicated Postgres container from the self-hosted stack for now, along with Homepage and Muximux entries and the active `litellm-secrets` declaration. Encrypted secret material in `secrets.yaml` is left untouched until it is intentionally cleaned up.

### Changed
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
- **Honcho stack**: Added a local Honcho API/worker/database/Redis stack for Hermes, wired Hermes to generate `~/.honcho/config.json` at startup, and added Homepage and Muximux entries.
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
