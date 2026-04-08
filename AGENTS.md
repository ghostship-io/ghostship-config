# Project Agent Memory

Use this file as the repo-specific operating memory.

Keep entries short, durable, and worth reloading. Do not turn this file into a
changelog.

## Workflow and Shared Defaults

- `home/config/AGENTS.md` is the user's cross-repo preference layer, not
  repo-specific guidance. Keep it concise, imperative, and high-signal.
- The shared workflow preferences require verified work to be committed before
  task completion.
- If a change needs a plan, implement it in a git worktree. If
  `using-git-worktrees` is available, activate it.
- For repo research, use `brainstorming` and `openspec-explore` when those
  capabilities are available.
- Use the `nix` skill for Nix-platform work and the `python` skill for Python
  work when they are available.
- Shared skills live under `home/config/skills/*` and are linked into
  `~/.agents/skills`. Repo-local OpenSpec assets live separately under
  `.codex/`, `.gemini/`, and `.opencode/`.
- The shared local skill is named `skill-creator` and is vendored from the
  upstream `skill-creator` package in `vercel-labs/agent-browser` `v0.9.3`.
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
- The Ghostship OpenSpec flow should keep proposal, design, and task work on
  `main`; `apply` should commit those planning artifacts on `main`, create or
  reuse `.worktrees/<name>/`, and start implementation from that worktree.
- The Ghostship OpenSpec archive flow should reconcile any matching change
  worktree back into `main`, commit the archive move on `main`, and then
  remove the worktree.
- `.envrc` uses `use flake`, so the root `flake.nix` must expose either
  `devShells.<system>.default` or `packages.<system>.default`.
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
- Develop-host `codex`, `gemini`, and `opencode` defaults are intentionally
  YOLO or allow-all; Codex injects its dangerous bypass flag unless approval or
  sandbox flags are already present, Gemini injects `--yolo`, and OpenCode
  keeps `permission = "allow"` in config. Those defaults are only live after
  the relevant NixOS rebuild or Home Manager switch.
- Develop hosts install `codex`, `gemini`, and `opencode` into the user-local
  npm prefix under `/home/nixos/.local/share/ghostship-agent-tools/npm`, and
  `ghostship-agent-maintenance.service` plus its timer own installing and
  upgrading those CLIs.
- `ghostship-agent-maintenance.timer` runs on boot and every `4h` with
  `Persistent=true` so missed runs fire after WSL resumes. It also refreshes
  global skills, refreshes managed Gemini extensions, bootstraps
  `~/.agent-browser` only when missing. On Nix develop hosts it must treat the system dependencies as already packaged and call `agent-browser install` without `--with-deps`, because distro package-manager bootstrapping is unsupported there and the wrapper already supplies the required shared libraries. It also rewrites `~/.config/opencode/opencode.json`
  from OpenRouter's ranked programming free frontend endpoint while preserving
  the `(ghostship-free)` label rewrite; do not reintroduce static OpenRouter
  model maps into the Nix-managed OpenCode
  config files.
- For an immediate user-triggered refresh, run `ghostship-agent-maintenance`
  directly instead of trying to start the system unit as an unprivileged user.
- Develop hosts should keep `ssh-agent` on the fixed
  `/run/user/1000/ssh-agent` socket directly; do not parse the `ssh-agent`
  command line in a post-start hook to rediscover the socket.
- Develop-host `sudo` caching is intentionally `timestamp_type=global` with a
  `12h` timeout so fresh agent PTYs share the same auth window.

## WSL and Windows

- Prefer `/mnt/c/...` for Windows files. Treat `/mnt/z` as a lazy mount that
  may need verification before use.
- `powershell.exe -File` does not accept WSL `/mnt/c/...` paths on this host.
  Use a Windows path such as `C:\...`.
- When launched from a WSL path, `powershell.exe` sees the working directory as
  a `\\wsl.localhost\...` UNC path. Use `Set-Location 'C:\...'` if a drive path
  is required.
- `wslpath -u 'C:\path'` converts to `/mnt/c/...` as expected, but
  `wslpath -w /home/nixos/...` returns a `\\wsl.localhost\NixOS\...` UNC path
  for WSL-native files rather than a `C:\...` path.
- Docker Desktop stores its WSL disk at
  `C:\Users\the owner\AppData\Local\Docker\wsl\disk\docker_data.vhdx` on this host.
- WSL registry `BasePath` values may be missing or use `\??\` / `\\?\` NT
  prefixes. Guard for that before using them as normal paths.

## Remote Access and Deployment

- Do not recommend or call `sudo`. It prompts for a password and blocks agent
  execution. Use a root shell or direct root SSH host instead.
- Use `ssh chill-penguin-root` for live work on `chill-penguin`. If that alias
  stops working, stop and ask the user to restore it.
- For prompt-driven remote work, start the command in detached tmux and drive it
  with `capture-pane` plus `send-keys`. Do not use blocking top-level SSH TTY
  sessions for agent workflows.
- If a remote deployment reaches a built system path but activation fails,
  apply the generation directly with
  `/nix/store/<system>/bin/switch-to-configuration switch`.
- This repo deploys through Git on the host. Do not ask the user to validate
  host-side changes until the required repo edits are committed and available to
  the host checkout.
- Preferred `chill-penguin` deploy flow:
  local `git push origin main`;
  remote `git -C /home/nixos/nixos-config pull --ff-only origin main`;
  remote `nixos-rebuild build --flake .#chill-penguin`;
  remote `./result/bin/switch-to-configuration switch`.
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

- Hermes on `chill-penguin` should use the upstream whole-home image contract: mount `/srv/apps/hermes/home` at `/home/hermes`, mount operator workspace data from `/srv/apps/hermes/workspace` directly at `/workspace`, and bind a seeded host path `/srv/apps/hermes/nix` at `/nix`. Seed `/srv/apps/hermes/nix` from the image before the first mounted start so the bundled store is not hidden behind an empty bind mount, and do not reintroduce repo-side startup shims or separate Honcho compatibility-state mounts.
- Hermes shared skill seed sources live in tracked repo files under
  `modules/self-hosted/hermes-seeds/shared/skills/<skill>/`. Seed them into
  `/srv/apps/hermes/home/seeds/shared/skills/<skill>/` only when the target
  directory is missing; once seeded, treat the host copy as operator-owned
  runtime state instead of forcing repo updates into the live container home.
- Hermes profile persona sources live in tracked repo files under
  `modules/self-hosted/hermes-seeds/profiles/<profile>/SOUL.md`. Seed them
  into `/srv/apps/hermes/home/seeds/profiles/<profile>/SOUL.md` only when the
  target file is missing; once seeded, treat the host copy as operator-owned
  runtime state instead of forcing repo updates into the live container home.
- PriceBuddy env files belong in `preStart`, not activation. Its durable API
  token is separate from the seeded app login and must be written as an
  `id|token` bearer value in `pricebuddy-agent.env`.
- PriceBuddy token sync must strip any existing token ID prefix before
  re-persisting `pricebuddy-agent.env`, and post-start verification should only
  gate Ghostship-managed wiring such as env generation, scraper reachability,
  and final bearer-token shape.
- On `chill-penguin`, Muximux intentionally omits Honcho while keeping
  PriceBuddy in the dropdown immediately after Bazarr; Homepage remains the
  place where Honcho stays visible.
- Muximux does not tolerate `user = "3000:3000"` in the current image; keep it
  on `0:3000`.
- Bazarr's authoritative config is `/srv/apps/bazarr/config/config.yaml`.
- CloakBrowser on `chill-penguin` should seed the managed default profile set as `assistant`, `operations`, `supervisor`, and `Changedetection`; do not reintroduce legacy `Direct` or `VPN` defaults. Keep the dedicated `Changedetection` profile automatically relaunched when the manager is healthy because changedetection.io is not profile-start-aware.
- n8n on `chill-penguin` should stay as a single SQLite-backed service with state persisted under `/srv/apps/n8n`; keep browser access behind Cloudflare, keep Hermes on the internal `http://n8n:5678` path with its dedicated `N8N_API_KEY` carried in `hermes-secrets`, and expect a one-time manual Muximux reorder after deployment so the live tile sits directly under Bazarr.
- Chaptarr on `chill-penguin` should follow the standard arr service pattern: keep its config under `/srv/apps/chaptarr`, mount the shared downloads root at `/downloads`, mount `/mnt/share/Library/Books` plus `/mnt/share/Library/Audiobooks` as separate library roots, and source its API key from a service-local `chaptarr-secrets` bundle. Grimmory should keep both library roots mounted because it is the primary consumption UI, and the live Muximux dropdown order should place Chaptarr after Bazarr and before `n8n` even if the host still needs a one-time manual reorder after deployment.
- Gluetun on `chill-penguin` should stay on Gluetun's custom-provider WireGuard path for PIA. Refresh the preferred PF-capable WireGuard server through the daily `gluetun-pia-selector` timer, cache the winner at `/srv/apps/gluetun/pia-wireguard-selection.json`, regenerate `/run/secrets/gluetun-runtime.env` from that cached winner during `podman-gluetun` startup, and keep PIA VPN-side port forwarding plus qBittorrent/VueTorrent port reconciliation wired through Gluetun's native hooks and the generic `/v1/portforward` monitor path.

## Secrets and Bootstrap

- `secrets.dec.yaml` is the ignored plaintext mirror. Do not commit it.
- Keep secret bundles in `secrets.dec.yaml` formatted with `|-` block scalars.
- Use service-local `*-secrets` bundles and service-local env names instead of
  shared `HOMEPAGE_*` bundles.
- `bootstrap.sh` is the installer-time host bootstrap entrypoint.
- Active spec, proposal, and task artifacts live under the repo-root
  `openspec/` tree.
