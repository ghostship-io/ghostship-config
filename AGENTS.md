# Project Agent Memory

Use this file as the repo-specific operating memory.

Keep entries short, durable, and worth reloading. Do not turn this file into a
changelog.

## Workflow and Shared Defaults

- `home/config/AGENTS.md` is the user's cross-repo preference layer, not
  repo-specific guidance. Keep it concise, imperative, and high-signal.
- The shared workflow preferences require verified work to be committed before
  task completion.
- If a change needs a plan, implement it in a git worktree.
- For repo research, use `brainstorming` and `openspec-explore` when those
  capabilities are available.
- Use the `nix` skill for Nix-platform work and the `python` skill for Python
  work when they are available.
- Shared skills live under `home/config/skills/*` and are linked into
  `~/.agents/skills`. Repo-local OpenSpec assets live separately under
  `.codex/`, `.gemini/`, and `.opencode/`.
- The shared local skill is named `skill-creator` and is vendored from the
  upstream `skill-creator` package in `vercel-labs/agent-browser` `v0.9.3`.
- Managed `skills.sh` installs are separate from the repo-managed
  `home/config/skills/*` inventory. Keep repo-owned shared skills curated under
  `home/config/skills/`, and let `ghostship-agent-maintenance` install or
  refresh any configured external `skills.sh` repos on each WSL develop host.
- Develop-host convergence should scrub the known stale `workmux
  set-window-status ...` commands from `~/.codex/hooks.json` so removed
  repo-managed tooling does not keep breaking Codex hooks, while preserving
  unrelated valid hook entries and warning instead of rewriting malformed JSON.
  Restart already-running Codex sessions after the relevant rebuild or switch
  if they were holding the stale hook state open.
- The `apply_patch` tool is currently broken in worktrees on this host. Use
  Python-based file edits instead of the `apply_patch` tool when editing from a
  worktree, and verify the diff immediately after each edit.
- Develop hosts replace Codex's built-in
  `~/.codex/skills/.system/skill-creator` path with a symlink to the managed
  shared `~/.agents/skills/skill-creator`, and
  `ghostship-agent-maintenance` reasserts that override after Codex updates.
- OpenSpec slash commands and agent assets are project-local. Refresh them by
  running `openspec update` in an OpenSpec-enabled repo.
- The develop-host `openspec` wrapper reapplies append-only Ghostship
  propose/apply/archive snippets after both `openspec init` and
  `openspec update` without a separate OpenSpec config directory.
- The managed `openspec` wrapper should keep upstream telemetry opted out by
  default with `DO_NOT_TRACK=1` and `OPENSPEC_TELEMETRY=0` so blocked egress
  does not spam harmless PostHog flush stack traces after successful commands.
- The Ghostship `propose` override should create or reuse the change
  worktree at the start, create proposal/design/tasks from that worktree, and
  end with a detailed overview of the full proposed change.
- The Ghostship `apply` override should commit planning artifacts in the
  active worktree, continue from that worktree, track issues found during
  apply, and update the current proposal instead of creating a new proposal or
  worktree when the user changes the work mid-apply.
- The Ghostship `archive` override should reconcile any matching change
  worktree back into `main`, commit the archive move on `main`, remove the
  worktree, try to leave `main` clean, and finish with a list of issues or
  follow-up work to consider next.
- `.envrc` uses `use flake`, so the root `flake.nix` must expose either
  `devShells.<system>.default` or `packages.<system>.default`.
- Default dev-shell package order currently matters on this host: keep `git`
  before `age` in `flake.nix` or Nix `2.31.3` can fail `nix print-dev-env` and
  `direnv` with `get-env.sh failed to produce an environment`.
- `nix eval .#...` reads the tracked flake source, not arbitrary untracked
  files in the working tree. Stage or track new files before relying on flake
  evaluation.
- On switched NixOS and NixOS-WSL systems, `/etc/hostname` and `/etc/wsl.conf`
  can be Nix-generated symlinks into the store. Do not rely on direct writes to
  those paths for persistence; keep durable hostname changes in declarative
  config and use runtime hostname changes only as best-effort bootstrap help.
- WSL host `hardware-configuration.nix` files should stay minimal like
  `launch-octopus`: keep real root/swap/kernel/platform facts, but drop
  generated WSL pseudo-filesystems such as `/mnt/wsl*`, `/usr/lib/wsl/*`,
  `/mnt/c`, and `/tmp/.X11-unix`.
- Managed Synology NFS mounts should use `hard`, not `soft`, on both WSL and
  NixOS clients so transient NAS stalls do not surface as client-side I/O
  errors or integrity failures during copies.
- WSL hosts enable `services.envfs` so Windows-side tooling that assumes FHS
  paths like `/usr/bin/bash` keeps working without host-local hacks, keep
  `wsl.wslConf.interop.appendWindowsPath = false` so `envfs` does not synthesize
  accidental Windows executables under `/usr/bin`, and back `/usr/bin/npm` plus
  `/usr/bin/npx` with explicit WSL wrapper entries that exec the real Nix store
  binaries instead of the broken raw Node shims.
- Develop-host `codex`, `gemini`, and `opencode` defaults are intentionally
  YOLO or allow-all; Codex injects its dangerous bypass flag unless approval or
  sandbox flags are already present, Gemini injects `--yolo`, and OpenCode
  keeps `permission = "allow"` in config. Those defaults are only live after
  the relevant NixOS rebuild or Home Manager switch.
- Develop hosts expose `agent-deck` through the same repo-managed wrapper
  pattern as the other agent CLIs.
- WSL desktop-facing OpenCode support uses the `opencode-server` user service
  on `127.0.0.1:8421`; do not add a repo-managed Paseo daemon.
- Develop hosts install `codex`, `gemini`, `opencode`, `paseo`, and `openspec` into the
  user-local npm prefix under
  `/home/nixos/.local/share/ghostship-agent-tools/npm`, and
  `ghostship-agent-maintenance.service` plus its timer own installing and
  upgrading those CLIs.
- `ghostship-agent-maintenance.timer` runs on boot and every `4h` with
  `Persistent=true` so missed runs fire after WSL resumes. It also ensures the
  managed `skills.sh` repos are installed globally, refreshes global skills,
  refreshes managed Gemini extensions, bootstraps `~/.agent-browser` only when
  missing, and keeps an explicit shell-capable runtime path in the generated
  maintenance script so npm and npx subprocesses can spawn `sh` under systemd.
  Gemini's generated system settings on develop hosts should omit the
  deprecated `experimental.plan` key so the managed launchers do not warn about
  stale read-only system config after the relevant rebuild or switch. On Nix
  develop hosts it must treat the system dependencies as already packaged and
  call `agent-browser install` without `--with-deps`, because distro
  package-manager bootstrapping is unsupported there and the wrapper already
  supplies the required shared libraries. It also rewrites
  `~/.config/opencode/opencode.json` from OpenRouter's ranked programming free
  frontend endpoint while preserving the `(ghostship-free)` label rewrite, and
  refreshes `agent-deck` from the latest upstream source release with the
  Ghostship web-mutations patch; do not reintroduce static OpenRouter model
  maps into the Nix-managed OpenCode config files or pin `agent-deck` back
  into the flake.
- For an immediate user-triggered refresh, run `ghostship-agent-maintenance`
  directly instead of trying to start the system unit as an unprivileged user.
- Develop hosts should keep `ssh-agent` on the fixed
  `/run/user/1000/ssh-agent` socket directly; do not parse the `ssh-agent`
  command line in a post-start hook to rediscover the socket.
- Develop-host `sudo` caching is intentionally `timestamp_type=global` with a
  `12h` timeout so fresh agent PTYs share the same auth window.
- If `git push` is unavailable or fails, stop and ask the user to fix push
  access instead of inventing another deployment path.
- Cloudflare SSH compatibility on `chill-penguin` depends on
  `services.openssh.macs` including plain `hmac-sha2-256` and
  `hmac-sha2-512` in addition to the `*-etm` variants.

## Nix, Builds, and Host Boot

- Use native Nix commands in repo docs and operations: `nix`, `nixos-rebuild`,
  and `switch-to-configuration`.
- Prefer `-L` for build logs.
- WSL hosts should cap `nix.settings.max-jobs` instead of inheriting `auto`;
  on `launch-octopus`, `auto` resolved to `22` and repeatedly left
  `nix-daemon` unresponsive under concurrent flake shells, agent sessions, and
  host builds.
- WSL hosts should also cap `nix.settings.cores`; leaving per-job core fanout
  at `0` lets each queued build try to use every reported host thread and can
  recreate the same memory-pressure stalls even after `max-jobs` is reduced.
- When using `buildLinux`-style functions, `modDirVersion` must match the
  kernel's expected version string exactly.
- If generated config depends on `sops`-managed secrets, put it in the relevant
  service `preStart`, not in `system.activationScripts`.
- For INI rewrites in activation or startup hooks, use `pkgs.yq-go` with
  `-p ini -o ini` and `pkgs.gnused` for follow-up `sed` fixes.
- Homepage `services.yaml` updates can leave stale entries behind when keys are
  removed from the generated source set. Add an explicit `pkgs.yq-go` prune step
  in activation for retired service entries instead of relying on
  `ghostship-config set` to delete them.
- For Apple Silicon:
  keep `hardware.firmwareCompression = "none"`;
  treat `/boot/asahi` as `chill-penguin`-specific;
  use `--impure` when firmware extraction reads `/boot/asahi`;
  use the official `nixos-apple-silicon` ISO build path.
- On `chill-penguin`, the working GRUB target is `/boot/grub/grub.cfg`, and the
  Apple Silicon boot chain requires a gzip-compressed kernel.

## Containers and Config Generation

- The NixOS OCI container module does not expose a generic `healthcheck`
  option. Keep healthchecks in Podman `extraOptions`.
- For Gluetun namespace dependents, declare both
  `after = [ "podman-gluetun.service" ]` and
  `bindsTo = [ "podman-gluetun.service" ]`.
- Keep Podman's native healthcheck cadence and use `--health-on-failure=kill`
  so systemd restart policies still work.
- Prefer `pull = "always";` for OCI containers in this repo.
- Use native `podman auto-update` for labeled containers and fully qualified
  image names when auto-update is enabled.
- Do not expose container ports on the host except for Plex.
- When a container can safely run as `3000:3000`, set it explicitly. Keep
  exceptions that need root startup behavior as root-run services.
- `ghostship-config.py` must accept multiple `--secrets-file` inputs.
- Use `yaml:` writes in `ghostship-config.py` when native YAML scalar types
  matter.
- `qBittorrent.conf` is an INI file. Treat it as INI and write WebUI settings
  under `[Preferences]` with `WebUI\\...` keys.
- Homepage's `resources` widget needs native YAML booleans. For host network
  stats on `chill-penguin`, mount `/sys/class/net` plus the matching
  `/sys/devices/platform` subtree, not the entire host `/sys`.

## Search and Browser Tooling

- `agent-browser` on the WSL develop hosts needs the wrapped Nix library path
  to launch Puppeteer's downloaded Chrome successfully.
- The managed `agent-browser` wrapper should default
  `AGENT_BROWSER_ENGINE=chrome` unless the caller overrides it, because recent
  upstream auto-launch behavior can drift onto Lightpanda and break the
  profile-based Chrome workflow used on develop hosts.
- Rebuilt Nix wrappers are not live until the new generation is activated. For
  immediate testing, run the evaluated store path directly.
- SearXNG config changes must be generated in `podman-searxng.preStart` so the
  service actually restarts with the new config.
- The practical internal SearXNG port in this stack is `8080`.
- Some SearXNG engine families require the base engine to remain present as a
  network anchor.
- Set `inactive = false` explicitly for default-off engines you intend to keep.
- Direct egress does not automatically fix blocked engines; validate engine
  behavior with live probes.
- Browser-side testing of the public SearXNG hostname requires Cloudflare
  Access or a tunnel from the develop host.

## RomM and Cloudflare

- Cloudflare Access in front of `romm.ghostship.io` can block iframe loads
  before RomM itself renders. Distinguish public-access issues from origin
  issues.
- RomM `4.8.0` started cleanly in an unpatched same-origin iframe harness on
  `chill-penguin`; a stale `postStart` bundle rewrite was the cause of the live
  startup failure, not the upstream container itself.
- Muximux should embed RomM through a same-origin `/romm/` reverse proxy to the
  internal `http://romm:8080` service, not the public `https://romm.ghostship.io`
  hostname.
- If the RomM iframe shim needs to load before the app bundle, inject it by
  replacing RomM's main module `src="/assets/index-...` tag in the proxied
  HTML, not by blindly prepending `<head>` content. The generic `<head>`
  injection path broke RomM's asset base and caused looping chunk imports.
- Current RomM bundles can ship `var z5={};` with no rewritable `BASE_URL`
  literal. Keep the `/romm/` proxy durable by injecting a real
  `<base href="/romm/">` into the proxied HTML so Vue Router detects the
  correct base at runtime, and treat the old `BASE_URL:"/"` rewrite as a
  compatibility fallback for older builds.
- Current `lscr.io/linuxserver/pyload-ng:latest` returns `401 UNAUTHORIZED` on
  `/api` even when healthy. Keep the Podman health check on the public
  `http://127.0.0.1:8000/favicon.ico` endpoint instead of the auth-protected
  API path.
- Repo edits to `modules/self-hosted/romm.nix` are not live until the host is
  rebuilt. Inspect the live container files before treating a repo change as
  tested.
- Validate future RomM iframe regressions against a live unpatched container
  before adding any new mitigation.
- Validate RomM iframe regressions against the live served bundle, not just the
  unit definition.

## Service-Specific Notes

- Hermes on `chill-penguin` should follow the current upstream `ghostship-hermes` `main` workstation contract: mount `/srv/apps/hermes/home` at `/home/hermes`, mount `/srv/apps/hermes/workspace` directly at `/workspace`, and bind `/srv/apps/hermes/nix` at `/nix`. Let the image own internal supervision, first-boot `/nix` seeding for an empty mount, and later boot-time reconciliation of `/nix/var/nix/profiles/per-user/hermes/ghostship-defaults` on a reused non-empty `/nix`; do not reintroduce repo-side startup shims, in-container `systemd` calls, or separate Honcho compatibility-state mounts.
- Hermes container-executed commands run against the image-seeded `/srv/apps/hermes/nix` store mounted at `/nix`, not the host generation's `/nix/store`. Do not embed host `${pkgs.*}` store paths in Hermes container healthchecks or other in-container commands unless that exact path is guaranteed to exist in the upstream image store; prefer in-container commands such as `curl` on `PATH` or image-provided store paths.
- Hermes managed runtime state lives at `/home/hermes/.hermes`, and repo-managed host wiring should pass supported downstream env through the container environment or env files instead of patching `/home/hermes/.hermes/.env` directly. Fixed workstation layout, XDG, ttyd, browser, and router-topology env are image-owned internals, not supported downstream overrides. Terminal sessions should continue to default to `/workspace` through the upstream image-owned terminal contract.
- `hermes-secrets` should carry the shared Hermes runtime provider env plus the generic single-agent `DISCORD_BOT_TOKEN` and `WEBHOOK_SECRET`, while `n8n-secrets` keeps the dedicated internal `N8N_API_KEY`; treat GitHub or Home Assistant env as optional future wiring unless a change explicitly adds them.
- Hermes utility env projection on `chill-penguin` should read only the required utility-facing values from service-local secret bundles or generated runtime env files, write the selected auth subset to `/srv/apps/hermes/runtime.env`, and supply upstream with the supported Discord env surface `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`, `DISCORD_FREE_RESPONSE_CHANNELS`, and `GHOSTSHIP_ROUTER_CHANNEL` plus the unchanged provider and utility pass-through vars. `DISCORD_HOME_CHANNEL` should stay pinned to `1491229269127598281`. `DISCORD_FREE_RESPONSE_CHANNELS` must include router `1492841053642817606`, the former Codex channel `1493462179725180959` as a normal free-response channel, and the current three Ghostship free-response channels `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`. Do not emit `GHOSTSHIP_CODEX_CHANNEL`, `BROWSER_CDP_URL`, or any `BROWSER_*_CDP_URL` default from the repo. Keep Synology on `http://192.168.200.106:5000/`, keep qBittorrent plus NZBGet URL-only while their control auth remains disabled in this stack, and keep the n8n contract narrowed to `N8N_URL` plus `N8N_API_KEY`.
- Hermes now treats Codex on `openai-codex/gpt-5.4` as the normal primary model lane, with fallback `opencode-go/minimax-m2.7`, router custom provider alias `agentic`, and default `agent.reasoning_effort = "medium"`.
- Hermes on `chill-penguin` should not seed any repo-managed default skills into `/srv/apps/hermes/home/.hermes/skills/`; the repo-managed runtime seed surface there is intentionally empty, and the image's bundled default skill seeding should own that path instead.
- Hermes root persona source now lives at `modules/self-hosted/hermes-seeds/SOUL.md` and seeds `/srv/apps/hermes/home/.hermes/SOUL.md` only when the target file is missing; once seeded, treat the host copy as operator-owned runtime state instead of forcing repo updates into the live container home.
- PriceBuddy env files belong in `preStart`, not activation. Its durable API
  token is separate from the seeded app login and must be written as an
  `id|token` bearer value in `pricebuddy-agent.env`.
- PriceBuddy token sync must strip any existing token ID prefix before
  re-persisting `pricebuddy-agent.env`, and post-start verification should only
  gate Ghostship-managed wiring such as env generation, scraper reachability,
  and final bearer-token shape.
- On `chill-penguin` arm64, `pricebuddy-scraper` can report healthy while real
  `/api/article` fetches still fail on Selenium driver acquisition; validate the
  scraper with an actual article request, not only the health endpoint.
- On `chill-penguin`, Muximux intentionally omits Honcho while keeping
  PriceBuddy in the dropdown immediately after Bazarr; Homepage remains the
  place where Honcho stays visible.
- Muximux does not tolerate `user = "3000:3000"` in the current image; keep it
  on `0:3000`.
- Bazarr's authoritative config is `/srv/apps/bazarr/config/config.yaml`.
- CloakBrowser consumer images live under `containers/` and are built locally into content-addressed `localhost/...` tags from Nix-managed contexts; `pricebuddy-scraper` uses the embedded binary plus stealth args, and `changedetection` uses an embedded local CloakBrowser Playwright session with `humanize=True` instead of the manager/CDP path.
- n8n on `chill-penguin` should stay as a single SQLite-backed service with state persisted under `/srv/apps/n8n`; keep browser access behind Cloudflare, keep Hermes on the internal `http://n8n:5678` path with its dedicated `N8N_API_KEY` carried in `n8n-secrets`, and expect a one-time manual Muximux reorder after deployment so the live tile sits directly under Bazarr.
- Chaptarr on `chill-penguin` should follow the standard arr service pattern: keep its config under `/srv/apps/chaptarr`, mount the shared downloads root at `/downloads`, mount `/mnt/share/Library/Books` plus `/mnt/share/Library/Audiobooks` as separate library roots, and source its API key from a service-local `chaptarr-secrets` bundle. Grimmory should keep both library roots mounted because it is the primary consumption UI, and the generated Muximux dropdown order should place Chaptarr before Bazarr.
- BookStack on `chill-penguin` should keep app state under `/srv/apps/bookstack`, MariaDB state under `/srv/apps/bookstack-db`, and `BOOKSTACK_APP_URL` pinned to the external `https://bookstack.ghostship.io` origin. Keep the initial in-app setup plus API token creation manual for now, keep the Hermes env projection wired to `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET`, and keep the generated Muximux tile immediately after Prowlarr.
- Gluetun on `chill-penguin` should stay on Gluetun's custom-provider WireGuard path for PIA. `podman-gluetun` should start from the cached winner at `/srv/apps/gluetun/pia-wireguard-selection.json` or do only a provisional latency pick when no cache exists, regenerate `/run/secrets/gluetun-runtime.env` from that active winner during startup, and rely on `gluetun-pia-selector` to rerank Vancouver port-forward-capable WireGuard servers 5 minutes after boot and every 8 hours thereafter. The selector should pin Vancouver, benchmark the top 10 Vancouver servers with a bounded generic HTTPS download pull, and restart Gluetun only when a materially faster Vancouver winner is found while keeping PIA VPN-side port forwarding plus qBittorrent/VueTorrent port reconciliation wired through Gluetun's native hooks and the generic `/v1/portforward` monitor path.
- qBittorrent 5.1.4 on `chill-penguin` can stay `disconnected` if it only binds to Gluetun by interface name (`tun0`). Reconcile `current_interface_address` to Gluetun's live `tun0` IPv4 as part of the Gluetun monitor or port-forward reconciliation, not just the interface name and listen port.

## Secrets and Bootstrap

- The tracked secret model lives under `secrets/`: `recipients.nix` composes
  SSH recipients and groups, `catalog.nix` declares logical-unit secret files
  plus exported fields, and `rules.nix` feeds `ragenix`.
- Runtime decryption uses SSH host `ed25519` keys. Human edit access uses the
  dedicated passwordless non-default key `~/.ssh/id_ed25519_ragenix`.
- Normal operator flow is direct `secret-edit <logical-secret-name>` against
  the tracked `.age` files. Use `secrets-list-keys` or `secret-list` to find
  names, and reserve `secret-rekey` for recipient changes.
- `secrets/rules.nix` paths are resolved relative to that file's own
  directory by `ragenix`; keep rule keys relative to `secrets/`, not repo
  root paths prefixed with `secrets/`.
- Use service-local `*-secrets` bundles and catalog-driven projections instead
  of shared catch-all `HOMEPAGE_*` bundles or repeated raw secret path wiring.
- `bootstrap.sh` is the installer-time host bootstrap entrypoint. It captures a
  temporary intake bundle with `hardware-configuration.nix`, metadata, and the
  host SSH `ed25519` public key. WSL2 bootstrap must generate that host key if
  it is missing.
- `references/host-intake/<hostname>/` is temporary staging for Codex-assisted
  host integration. Remove it after Codex finishes integrating the host.
- Active spec, proposal, and task artifacts live under the repo-root
  `openspec/` tree.
