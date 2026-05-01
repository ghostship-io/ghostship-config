# Project Agent Memory

Use this file as the repo-specific operating memory.

Keep entries short, durable, and worth reloading. Do not turn this file into a
changelog.

## Workflow and Shared Defaults

- `home/config/AGENTS.md` is the user's cross-repo preference layer, not
  repo-specific guidance. Keep it concise, imperative, and high-signal.
- The shared workflow preferences require verified work to be committed before
  task completion.
- After finishing work in a Codex worktree, merge the result into local `main`,
  push `main`, and deploy Boomer when reachable.
- If a change needs a plan, implement it in a git worktree.
- For repo research, use `brainstorming` when it is available.
- Use the `nix` skill for Nix-platform work and the `python` skill for Python
  work when they are available.
- Shared skills live under `home/config/skills/*` and are linked into
  `~/.agents/skills`.
- `codex-queue` is for long manual-review queues only; its tooling may split,
  launch, monitor, validate, and merge, but must not automate final item
  judgments.
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
- Develop hosts replace Codex's built-in
  `~/.codex/skills/.system/skill-creator` path with a symlink to the managed
  shared `~/.agents/skills/skill-creator`, and
  `ghostship-agent-maintenance` reasserts that override after Codex updates.
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
- WSL hosts use patched `services.envfs` so Windows-side tooling can resolve
  Linux/FHS paths such as `/usr/bin/bash`, keep
  `wsl.wslConf.interop.appendWindowsPath = true` for desktop interop, and patch
  envfs to filter Windows/DrvFS PATH binaries, including WSL `9p` mounts with
  `aname=drvfs`, out of `/usr/bin` while allowing metadata/path probes so
  shebang launchers such as npm and npx can reopen envfs-synthesized entries
  without wrappers.
- Develop-host `codex`, `gemini`, and `opencode` defaults are intentionally
  YOLO or allow-all; Codex injects its dangerous bypass flag unless approval or
  sandbox flags are already present, Gemini injects `--yolo`, and OpenCode
  keeps `permission = "allow"` in config. Those defaults are only live after
  the relevant NixOS rebuild or Home Manager switch.
- Develop hosts expose `agent-deck` through the same repo-managed wrapper
  pattern as the other agent CLIs.
- WSL desktop-facing OpenCode support uses the `opencode-server` user service
  on `127.0.0.1:4096`; do not add a repo-managed Paseo daemon.
- Develop hosts install `codex`, `gemini`, `opencode`, and `paseo` into the
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

## WSL and Windows

- Prefer `/mnt/c/...` for Windows files. Treat `/mnt/z` as a lazy mount that
  may need verification before use.
- Windows PATH import is enabled on WSL hosts, but repo scripts should prefer
  explicit `/mnt/c/...` paths or repo-managed wrappers such as `wsl-open` and
  `win-powershell` when deterministic behavior matters.
- WSL activation should stop `mnt-z.automount` and unmount any live `/mnt/z`
  NFS mount before reloading generated mount units so switches do not fail on
  stale `/mnt/z` mount state.
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
- WSL `envfs` or `wsl.extraBin` changes can require a full WSL distro restart
  after a `nixos-rebuild switch` before refreshed `/usr/bin/...` or `/bin/...`
  entries appear in the live instance.

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
- Boomer Kuwanger's emulation profile is owned by `modules/emulation`: keep
  ES-DE mandatory, put new code in the focused submodule rather than the
  aggregator, keep the host disk layout label-based (`BOOT`, `swap`, `nixos`,
  `roms`) with the `nixos` Btrfs filesystem mounted at `/`, no `/fast` mount,
  and `/srv/emulation/roms` mounted from the `roms` Btrfs filesystem. Keep
  OpenSSH enabled with root key login only and no password or
  keyboard-interactive authentication. Keep Wi-Fi available but constrain
  NetworkManager Wi-Fi profiles to 5 GHz instead of rfkilling the radio, so
  Bluetooth stays usable and SSH remains reachable. The Wi-Fi bootstrap service
  should wait for NetworkManager, clear stale Wi-Fi interface pins, and bring up
  saved 5 GHz profiles if autoconnect does not fire. Keep BlueZ's unused
  BAP/CSIP LE Audio plugins disabled unless LE Audio hardware becomes a
  requirement; Switch-mode controllers do not need them. Boomer should boot
  directly into the ES-DE/Gamescope kiosk session; keep `start-esde` available
  as a manual maintenance command. Public
  emulation commands and services intentionally avoid a `boomer-` prefix. The
  ES-DE AppImage under Gamescope needs the session service to clear capability
  bounding/ambient sets or bubblewrap exits with unexpected capabilities; the
  same is true for root-reexec smoke/perf test units. ES-DE-launched games
  should reuse the frontend display session and not start nested Gamescope;
  direct tty launches may still wrap emulators in Gamescope. Use the official
  ES-DE AppImage package unless a source build is explicitly revisited. PipeWire may
  prefer USB audio adapters on Boomer; keep
  `audio-route` in the ES-DE session and emulator launcher so the current
  available AMD HDMI/DP profile becomes the default sink unless the Boomer
  Bluetooth Settings TUI has selected a connected Bluetooth audio sink. Keep
  visible Boomer ES-DE utilities collapsed to Bluetooth Settings, Wi-Fi
  Settings, and system power/session actions; the settings entries should stay
  large-font, keyboard-and-controller friendly TUIs with a dark two-column
  layout, left-side actions, and right-side selected-action status. Hide
  host-only BlueZ fields such as discoverable and pairable from the main
  Bluetooth status, but keep the discovering/scanning state visible because it
  tells the user whether Boomer is actively looking for devices. Keep full
  status blocks on the Status action only; other actions should show concise
  help so the right pane stays contained. Player assignment should allow
  keyboard as a player device, with B/Esc canceling before assignment. Let the
  terminal handle keyboard input and keep the raw `/dev/input` reader limited
  to real controller navigation event nodes, excluding Switch Pro IMU motion
  devices and analog-stick idle noise. In the ES-DE
  Gamescope session these TUIs should launch through Xwayland `xterm`; `foot`
  fails there because Gamescope does not expose the Wayland subcompositor it
  needs. Bluetooth pairing scans should use `bluetoothctl --timeout` and parse
  live `[NEW] Device` output, not rely only on the post-scan device cache; pair
  commands should register their own BlueZ agent. Keep a `Show Paired` item
  directly under Bluetooth status. Controller LED writes should target the
  matched controller sysfs root, avoid generic fallbacks that light unrelated
  player LEDs, and minimize repeated sysfs writes because each LED write sends a
  Nintendo output subcommand over Bluetooth. For Boomer's MediaTek MT7921/MT7961
  combo radio, prefer BR/EDR mode, keep Wi-Fi on 5 GHz with Wi-Fi power save and
  MT7921e ASPM disabled, remove Bluetooth `SNIFF` link policy from connected
  Switch Pro controllers to favor input latency over battery life, leave
  joycond/cemuhook inactive by default, and keep focused BlueZ/`hid-nintendo`
  diagnostics available on demand under
  `/srv/emulation/logs/`, not continuously enabled during normal play. Avoid
  continuous `btmgmt` polling in background services; bound Bluetooth
  diagnostics and startup `btmgmt` tuning so a busy controller cannot stall
  activation. Keep normal Bluetooth priority boosts conservative: `bluetoothd`
  may use a small negative nice value and higher CPU weight, and system D-Bus
  may get a modest CPU weight boost; do not enable realtime scheduling or IRQ
  pinning unless a measured emulator-load test justifies it. Player order should
  compact connected Switch controllers into
  the lowest open slots while preserving relative order, with reconnecting
  controllers joining at the end. Trigger a one-shot controller reconcile from
  controller input add events and debounced BlueZ connected-property changes;
  serialize LED/order writes so the background loop and one-shot apply cannot
  race, update the background state marker from one-shot applies, and rate-limit
  changed LED writes to roughly one write every half second. Merge supported USB
  HID input nodes into player reconciliation; Bluetooth controller connection
  truth must come from BlueZ so stale Bluetooth HID nodes do not keep receiving
  LED writes after disconnect or radio failure. Some 8BitDo wired USB modes
  expose `2dc8:301a` via `hid-generic`, which should be tracked as an
  input-only player identity while connected because it can provide input but
  not Nintendo player LED sysfs controls.
  Do not start-limit one-shot LED applies during fast reconnect cycles, but
  avoid direct rapid `controller-leds apply` fan-out or force-writing
  already-correct LEDs because hid-nintendo output reports can wedge the
  Bluetooth daemon. For Boomer
  emulation changes, deploy to Boomer before calling the work complete: push
  main, merge on `/root/nixos-config`, build, switch, and verify live services.
  Smoke
  tests should not add runtime ROM extraction; manually extract only proven
  failing smoke copies and point `/srv/emulation/config/smoke/roms.json` at the
  launchable file. Root-run smoke tests on kiosk-mode Boomer should restore
  `greetd`, not `getty@tty1`, after borrowing tty1 so ES-DE comes back instead
  of a login prompt. Keep Boomer's emulator defaults RetroAchievements-aligned where
  practical: Beetle SuperGrafx for PCE/PCE CD, FCEUmm for NES/FDS, Azahar for
  3DS, standalone PCSX2 for PS2, standalone PPSSPP for PSP, and no Gamescope
  FSR; use emulator-native scaling plus NNEDI3/sharp RetroArch shaders. Keep
  perf tests in `modules/emulation/perf.nix`, launch through `run-emulator`,
  and write recommendations instead of auto-mutating runtime profiles. Use the
  repo-pinned official Ryubing Canary package from
  `modules/emulation/ryubing-canary-pin.nix`, refreshing it with
  `scripts/update-ryubing-canary` before rebuilding when upstream advances.
  Switch `.nro` homebrew can keep sibling `data/` assets beside the ROM;
  `run-emulator` links that directory into Ryubing's emulated SD card at launch.
  Xemu launches with an explicit Nix-generated
  `/srv/emulation/xdg/share/xemu/xemu/xemu.toml`; keep Xbox machine paths in
  that config instead of relying on Xemu's implicit config discovery. Keep
  `general.show_welcome = false` there or Xemu suppresses the configured BIOS
  and stops in the first-run machine wizard. ES-DE matches Xbox files by final
  `.iso` suffix, so name launchable XISOs `.xiso.iso` and keep redump backups
  from ending in `.iso`.
  Keep Boomer's ES-DE ROM folder names aligned exactly with
  `/mnt/z/Library/ROMs/roms`; Doom uses `Fantasy - GZDoom (2005)` with
  Batocera-style `.gzdoom` launchers at the ROM-folder top level and assets
  underneath that folder. PICO-8 needs an explicit Gamescope Xwayland server on
  Boomer because its SDL path uses X11. Boomer's managed ES-DE UI defaults are
  manufacturer/hardware/release systems sorting, visible clock, Switch Pro
  controller prompts, all-controller ES-DE menu input, Hawaii standard time, and
  a visible clock using ES-DE-supported `%H:%M` formatting; true 12-hour clock
  text needs a source-level ES-DE formatter patch. Boomer's controller
  automation should treat Switch Pro style controllers as the primary path, keep
  LEDs on Switch-style player count patterns only, and avoid auto-assigning
  audio devices or generic peripherals as players. Boomer's Switch Pro
  shortcuts should stay Switch-style:
  Select+X is the quick-menu chord, Square/Capture is native console Home only
  where explicitly configured and otherwise no-op, Select/Minus is the hotkey
  modifier, Star/Home is a controller-local turbo button when exposed, and
  Select+Start double-press is a normal emulator exit with a 5-second
  force-kill fallback.
  Controller Maps should stay text-only with a compact two-column button map
  above hotkeys, no ASCII controller art. Keep N64 A/B direct on physical
  Switch A/B, and launch GZDoom with the managed Boomer controls cfg so
  left stick/D-pad move, right stick looks, Use/Confirm is A, Jump/Back is B,
  Select/Minus toggles map, Y toggles crouch, X is unbound, L/R select
  previous/next weapon, ZL is alt fire, ZR is fire, `+` opens menu, and
  Square/Capture is unbound. GZDoom's SDL
  `[Joy:JS:*]` axis map must be seeded so
  Switch Pro axis 0/1 are strafe/forward, axis 2 is yaw, axis 3 is pitch with
  reduced scale, trigger axes 4/5 are action buttons only, D-pad hat axes can
  move/pan, and unused axes are disabled.
  Boomer's probed kernel Switch Pro raw map is documented in
  `docs/boomer-kuwanger-emulation.md`; use that table instead of inferring
  physical labels from emulator names.
  Boomer's live SDL joystick path maps GZDoom physical B/A/X/Y to
  Joy1/Joy2/Joy3/Joy4, `-` to Joy5, `+` to Joy7, L1/R1 to Joy10/Joy11,
  ZL/ZR to Joy13/Joy14, and the D-pad to POV1. Keep only the GZDoom menu A/B
  package patch unless a future live probe proves another package patch is
  required.
  WiiWare games should stay as extracted `.wad` files in the Wii ROM
  folder so ES-DE can launch them through Dolphin. Dolphin runtime config/cache
  can be reset, but preserve `/srv/emulation/xdg/share/dolphin-emu` because it
  contains save/NAND state.
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
- PyLoad's LinuxServer image starts with `--storagedir /downloads` by default,
  which overrides and rewrites `pyload.cfg`. Keep the service run override if
  the managed app config should own `general.storage_folder`.
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
- Hermes uses s6-overlay in the container; keep the Podman stop signal on `SIGTERM`, not `SIGRTMIN+3`.
- Hermes managed runtime state lives at `/home/hermes/.hermes`, and repo-managed host wiring should pass supported downstream env through the container environment or env files instead of patching `/home/hermes/.hermes/.env` directly. Fixed workstation layout, XDG, ttyd, browser, and router-topology env are image-owned internals, not supported downstream overrides. Terminal sessions should continue to default to `/workspace` through the upstream image-owned terminal contract.
- `hermes-secrets` should carry the shared Hermes runtime provider env plus the generic single-agent `DISCORD_BOT_TOKEN` and `WEBHOOK_SECRET`, while `n8n-secrets` keeps the dedicated internal `N8N_API_KEY`; treat GitHub or Home Assistant env as optional future wiring unless a change explicitly adds them.
- Hermes utility env projection on `chill-penguin` should read only the required utility-facing values from service-local secret bundles or generated runtime env files, write the selected auth subset to `/srv/apps/hermes/runtime.env`, and supply upstream with the supported Discord env surface `DISCORD_ALLOWED_USERS`, `DISCORD_HOME_CHANNEL`, `DISCORD_FREE_RESPONSE_CHANNELS`, `GHOSTSHIP_CODEX_CHANNEL`, and `DISCORD_WEBHOOK_CHANNEL` plus unchanged provider and utility pass-through vars. `GHOSTSHIP_CODEX_CHANNEL` is `1492841053642817606`, `DISCORD_WEBHOOK_CHANNEL` is `1491229248856260799`, `DISCORD_HOME_CHANNEL` should stay pinned to `1491229269127598281`, and `DISCORD_FREE_RESPONSE_CHANNELS` must include `1492841053642817606`, `1493462179725180959`, `1491229269127598281`, `1491229248856260799`, and `1491229299452412044`. Do not emit `GHOSTSHIP_ROUTER_CHANNEL`, `BROWSER_CDP_URL`, or any `BROWSER_*_CDP_URL` default from the repo. Keep Synology on `http://192.168.200.106:5000/`, keep qBittorrent plus NZBGet URL-only while their control auth remains disabled in this stack, and keep the n8n contract narrowed to `N8N_URL` plus `N8N_API_KEY`.
- Hermes now treats the local router as primary for normal model routing, keeps Codex on `openai-codex/gpt-5.5` for the forced Discord Codex channel, uses `opencode-go/minimax-m2.7` as the paid fallback lane, uses Firecrawl as the managed web backend, and defaults `agent.reasoning_effort = "medium"`.
- Hermes uses image-managed Bitwarden Password Manager CLI `bw` state at `/home/hermes/.local/state/bitwarden-cli`; keep `BITWARDENCLI_APPDATA_DIR` aligned with that path and carry `BW_CLIENTID`, `BW_CLIENTSECRET`, and `BW_PASSWORD` through `hermes-secrets` when Bitwarden login is needed.
- Hermes on `chill-penguin` should not seed any repo-managed default skills into `/srv/apps/hermes/home/.hermes/skills/`; the repo-managed runtime seed surface there is intentionally empty, and the image's bundled default skill seeding should own that path instead.
- Hermes root persona source now lives at `modules/self-hosted/hermes-seeds/SOUL.md` and seeds `/srv/apps/hermes/home/.hermes/SOUL.md` only when the target file is missing; once seeded, treat the host copy as operator-owned runtime state instead of forcing repo updates into the live container home.
- PriceBuddy env files belong in `preStart`, not activation. Its durable API
  token is separate from the seeded app login and must be written as an
  `id|token` bearer value in `pricebuddy-agent.env`.
- PriceBuddy token sync must strip any existing token ID prefix before
  re-persisting `pricebuddy-agent.env`, and post-start verification should only
  gate Ghostship-managed wiring such as env generation, scraper reachability,
  and final bearer-token shape.
- On `chill-penguin`, `pricebuddy-scraper` now runs as a local CloakBrowser+Playwright sidecar; keep its health check pointed at `/health`, which must validate a real browser launch rather than only process liveness.
- On `chill-penguin`, Muximux intentionally omits Honcho while keeping
  PriceBuddy in the dropdown immediately after Bazarr; Homepage remains the
  place where Honcho stays visible.
- Muximux does not tolerate `user = "3000:3000"` in the current image; keep it
  on `0:3000`.
- Bazarr's authoritative config is `/srv/apps/bazarr/config/config.yaml`.
- CloakBrowser consumer images live under `containers/` and are built locally into content-addressed `localhost/...` tags from Nix-managed contexts; `pricebuddy-scraper` and `changedetection` both run embedded local CloakBrowser Playwright sessions with `humanize=True` instead of the manager/CDP path.
- The standalone `cloakhq/cloakbrowser-manager` service is retired on `chill-penguin`; keep Changedetection, PriceBuddy scraper, Firecrawl Playwright, and Hermes on their embedded or image-owned browser paths only.
- n8n on `chill-penguin` should stay as a single SQLite-backed service with state persisted under `/srv/apps/n8n`; keep browser access behind Cloudflare, keep Hermes on the internal `http://n8n:5678` path with its dedicated `N8N_API_KEY` carried in `n8n-secrets`, and expect a one-time manual Muximux reorder after deployment so the live tile sits directly under Bazarr.
- Chaptarr on `chill-penguin` should follow the standard arr service pattern: keep its config under `/srv/apps/chaptarr`, mount the shared downloads root at `/downloads`, mount `/mnt/share/Library/Books` plus `/mnt/share/Library/Audiobooks` as separate library roots, and source its API key from a service-local `chaptarr-secrets` bundle. Grimmory should keep both library roots mounted because it is the primary consumption UI, and the generated Muximux dropdown order should place Chaptarr before Bazarr.
- BookStack on `chill-penguin` should keep app state under `/srv/apps/bookstack`, MariaDB state under `/srv/apps/bookstack-db`, and `BOOKSTACK_APP_URL` pinned to the external `https://bookstack.ghostship.io` origin. Keep the initial in-app setup plus API token creation manual for now, keep the Hermes env projection wired to `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET`, and keep the generated Muximux tile immediately after Prowlarr.
- Gluetun on `chill-penguin` should stay on Gluetun's custom-provider WireGuard path for PIA. `podman-gluetun` should start from the cached winner at `/srv/apps/gluetun/pia-wireguard-selection.json` or do only a provisional latency pick when no cache exists, regenerate `/run/secrets/gluetun-runtime.env` from that active winner during startup, and rely on `gluetun-pia-selector` to rerank Vancouver port-forward-capable WireGuard servers 5 minutes after boot and every 8 hours thereafter. The selector should pin Vancouver, benchmark the top 10 Vancouver servers with a bounded generic HTTPS download pull, and restart Gluetun only when a materially faster Vancouver winner is found while keeping PIA VPN-side port forwarding plus qBittorrent/VueTorrent port reconciliation wired through Gluetun's native hooks and the generic `/v1/portforward` monitor path.
- qBittorrent 5.1.4 on `chill-penguin` can stay `disconnected` if it only binds to Gluetun by interface name (`tun0`). Reconcile `current_interface_address` to Gluetun's live `tun0` IPv4 as part of the Gluetun monitor or port-forward reconciliation, not just the interface name and listen port.
- Keep VueTorrent/qBittorrent torrent data under `/downloads/Torrent` and incomplete data under `/downloads/Torrent/.incomplete`; do not let torrent `.parts` files land in the shared `/downloads` root.
- Managed qBittorrent queue policy is 5 active downloads, 20 active torrents, slow torrents excluded from active queue limits, a 20 MB/s global download cap, and post-completion rechecks enabled.
- Managed qBittorrent errored-torrent recovery retries every 5 minutes without a per-torrent retry cap.

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
- Keep self-hosted secret activation limited to `self-hosted-runtime` catalog
  units; emulation secrets are declared by `modules/emulation`.
- `bootstrap.sh` is the installer-time host bootstrap entrypoint. It captures a
  temporary intake bundle with `hardware-configuration.nix`, metadata, and the
  host SSH `ed25519` public key. WSL2 bootstrap must generate that host key if
  it is missing.
- `references/host-intake/<hostname>/` is temporary staging for Codex-assisted
  host integration. Remove it after Codex finishes integrating the host.
