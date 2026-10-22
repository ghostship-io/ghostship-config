# Host and service operating notes

Read only the section relevant to the host or service being changed. These
notes describe the NixOS fleet; inspect the current declarative configuration
and live state before relying on a historical version or path. For the running
T3 Code environment, use [container-workflow.md](container-workflow.md).

## Workflow and Shared Defaults

- This repo also runs in the T3 Code container at `/workspace/nixos-config`
  as `t3code`. Use `nix develop -c scripts/check` for local validation and
  `nix develop .#browser` only when local Playwright browsers are needed.
  The container owns Codex, OpenCode, and Antigravity; do not apply the develop
  host's Home Manager profile or agent maintenance here. Deploy NixOS changes
  through Git and direct root SSH on the target host, not local activation.
- In T3 Code, `t3code-shared-agents` installs the existing
  `/workspace/ghostship-agent` package and shares its skill catalog through
  `~/.agents/skills` and `~/.gemini/config/skills`. Keep provider credentials,
  plugin settings, and built-in Codex skills separate from this shared catalog.
- `home/config/AGENTS.md` is the user's cross-repo preference layer, not
  repo-specific guidance. Keep it concise, imperative, and high-signal.
- The shared workflow preferences require verified work to be committed before
  task completion.
- In worktrees, work on a named branch and open a GitHub PR before returning to
  the user. Push the branch, open the PR as draft/WIP, treat GitHub Actions as
  the primary branch/feature validation path, set up GitHub CI tests for GitHub
  repos when absent or insufficient, optimize CI to conserve free-plan minutes,
  configure workflows to cancel superseded runs so only the latest push per
  branch continues, review and resolve or explicitly reject Codex comments,
  resolve failing CI and merge conflicts, then mark the PR ready/non-WIP before
  handoff when it is ready for the user to merge. Leave PR merges to the user.
- Use the `nix` skill for Nix-platform work and the `python` skill for Python
  work when they are available.
- The old repo-managed shared skill inventory is retired; do not restore
  `home/config/skills/{codex-queue,github-pr-workflow,nix,python,skill-creator,ssh,wsl2}`
  inventory unless the skill model is explicitly revisited.
- Develop hosts rely on the installed global `skills` CLI and linked local
  Ghostship workflow skills under `home/config/skills/ghostship-*`.
- The global `skills` CLI uses
  `$XDG_STATE_HOME/skills/.skill-lock.json` during agent maintenance; retired
  skill cleanup must scrub that lock as well as legacy
  `~/.agents/.skill-lock.json` state or maintenance will reinstall the skill.
- Develop-host convergence should scrub the known stale `workmux
  set-window-status ...` commands from `~/.codex/hooks.json` so removed
  repo-managed tooling does not keep breaking Codex hooks, while preserving
  unrelated valid hook entries and warning instead of rewriting malformed JSON.
  Restart already-running Codex sessions after the relevant rebuild or switch
  if they were holding the stale hook state open.
- Develop hosts use `pkgs.fish` directly as the login shell.
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
- WSL hosts keep `wsl.wslConf.interop.appendWindowsPath = true` for desktop
  interop and use explicit writable FHS shims under `ghostship.wsl.fhsShims`
  instead of `services.envfs`; add new hardcoded `/bin/...` or `/usr/bin/...`
  needs there, and leave `/usr/bin/docker-credential-desktop.exe` for Docker
  Desktop to create at runtime.
- Develop-host `codex`, `gemini`, and `opencode` defaults are intentionally
  YOLO or allow-all; Codex injects its dangerous bypass flag unless approval or
  sandbox flags are already present, Gemini injects `--yolo`, and OpenCode
  keeps `permission = "allow"` in config. Those defaults are only live after
  the relevant NixOS rebuild or Home Manager switch.
- Retired develop tools Paseo, Agent Deck, and the WSL OpenCode desktop server
  should stay removed; use cleanup modules for stale artifacts instead of
  reintroducing their services.
- Develop hosts install `codex`, `gemini`, and `opencode` into the
  user-local npm prefix under
  `/home/nixos/.local/share/ghostship-agent-tools/npm`, and
  `ghostship-agent-maintenance.service` plus its timer own installing and
  upgrading those CLIs.
- Hosts with `ghostship.host.roles.t3worker = true` also install `t3`, `grok`,
  `claude`, and `cursor` through the same maintenance service. Workers are
  standalone Windows development boxes: do not install the `ghostship-agent`
  tool package, clone its catalog, or project Ghostship secrets onto them. They
  link only the small skill set under `home/config/skills/`.
  `modules/agent-worker` owns the worker unit and timer; see
  [WSL2 T3 Code workers](wsl-t3-workers.md).
- Worker hosts use the unified `home/config/AGENTS.md`, which carries the
  common preferences plus WSL2-specific guidance. The Docker T3 Code container
  uses the catalog's own generated guidance; the two instruction sources stay
  separate by design.
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
  frontend endpoint while preserving the `(ghostship-free)` label rewrite; do
  not reintroduce static OpenRouter model maps into the Nix-managed OpenCode
  config files.
- For an immediate user-triggered refresh, run `ghostship-agent-maintenance`
  directly instead of trying to start the system unit as an unprivileged user.
- Develop hosts should keep `ssh-agent` on the fixed
  `/run/user/1000/ssh-agent` socket directly; do not parse the `ssh-agent`
  command line in a post-start hook to rediscover the socket.
- Develop-host `sudo` caching is intentionally `timestamp_type=global` with a
  `12h` timeout so fresh agent PTYs share the same auth window.

## WSL and Windows

- Prefer `/mnt/c/...` for Windows files. Treat `/mnt/share` as a lazy mount that
  may need verification before use.
- Windows PATH import is enabled on WSL hosts, but repo scripts should prefer
  explicit `/mnt/c/...` paths or repo-managed wrappers such as `wsl-open` and
  `win-powershell` when deterministic behavior matters.
- WSL activation should stop `mnt-share.automount`, clear any stale
  `mnt-z.automount`, and unmount any live `/mnt/share` or `/mnt/z` NFS mount
  before reloading generated mount units so switches do not fail on stale share
  mount state.
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
- WSL FHS shim changes can require a full WSL distro restart after a
  `nixos-rebuild switch` before refreshed `/usr/bin/...` or `/bin/...` entries
  appear in the live instance.

## Remote Access and Deployment

- Do not recommend or call `sudo`. It prompts for a password and blocks agent
  execution. Use a root shell or direct root SSH host instead.
- Use `ssh chill-penguin` for live work on `chill-penguin`.
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
  remote `scripts/activate-host --toplevel ./result`.
  `scripts/activate-host` sets the system profile before the switch and
  verifies that `/run/current-system` and the system profile name the same
  generation. A bare `switch-to-configuration switch` does not record the
  system generation, and a reboot then reverts to the profile's generation.
- If `git push` is unavailable or fails, stop and ask the user to fix push
  access instead of inventing another deployment path.
- Cloudflare SSH compatibility on `chill-penguin` depends on
  `services.openssh.macs` including plain `hmac-sha2-256` and
  `hmac-sha2-512` in addition to the `*-etm` variants.
- The agent SSH key runs `ghostship-ssh-command-guard` as its forced command
  (`modules/self-hosted/ssh-command-guard.nix`). It refuses a recursive content
  read rooted at `/etc`, `/root`, `/home`, `/var/lib` or `/` with exit status
  126 and a journal line under the `ghostship-ssh-command-guard` tag, and runs
  every other command unchanged. Read named files only; a search of the host is
  not a named file. The owner's own keys are authorized without a forced
  command.

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
  not Nintendo player LED sysfs controls. Boomer's current USB pairing proof
  helper can read and trust a `057e:2009` controller MAC over hidraw, but BlueZ
  connect while the controller remains USB-attached fails with
  `br-connection-create-socket`. USB-assisted Bluetooth pairing status must
  distinguish BlueZ paired/trusted state from wireless connected state: paired
  means BlueZ reports Paired, Bonded, and Trusted; connected means BlueZ reports
  Connected after the controller reconnects wirelessly. Do not show an ES-DE
  success popup until the intended BlueZ state is verified. Gamescope/ES-DE
  does not provide `org.freedesktop.Notifications`; pairing messages need an
  explicit kiosk-visible Xwayland overlay or ES-DE patch, not `notify-send`.
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
  FSR; use emulator-native scaling plus the managed RetroArch `global.slangp`
  shader preset. RetroArch should use the managed base `retroarch.cfg`, generated
  `retroachievements.cfg` append config for credentials, XDG `global.slangp`,
  and XDG per-core `.opt` files; do not add system override or per-core `.cfg`
  layers unless that contract is explicitly changed. Keep
  N64 on RetroArch Mupen64Plus-Next with GLideN64 3x native resolution and the
  global shader preset; ParaLLEl N64 stays installed only as a fallback core.
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
  If Hunter: The Reckoning - Redeemer falls back to the Xemu "please insert
  disc" dashboard while `info block` shows the XISO mounted, suspect the
  acquisition/repack source before launcher config. A partial Redump download
  can still repack into an internally listable XISO that passes a weak
  `default.xbe` check; reacquire the Redump ZIP and repack before changing
  Xemu wiring.
  Keep Boomer's ES-DE ROM folder names aligned exactly with
  `/mnt/z/Library/ROMs/roms`; Doom uses `Fantasy - GZDoom (2005)` with
  Batocera-style `.gzdoom` launchers at the ROM-folder top level and assets
  underneath that folder. PCSX2 2.6.3 does not boot `.m3u` directly on Boomer;
  keep PS2 playlist support in `run-emulator` by resolving the first listed
  disc before launching PCSX2. PICO-8 needs an explicit Gamescope Xwayland server on
  Boomer because its SDL path uses X11; keep `pico8-hotkeys` as the default and
  plain `pico8` as the fallback alternate with the managed PICO-8 `-home` path.
  Ryubing needs `MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE=1` with Boomer's
  preferred Vulkan device or it can still choose the 780M iGPU even when
  `MESA_VK_DEVICE_SELECT=1002:73ef` is set; set Ryubing `preferred_gpu` to
  `0x1002_0x73EF`, not the display name. Ryubing 1.3.279 needs SDL3
  `input_config` entries for connected controllers; generate IDs with
  Ryubing's SDL3 stable GUID format like
  Ryubing's `SDL3GamepadDriver.GenerateGamepadId` convention: convert the SDL3
  GUID to Ryubing's GUID string, replace the first four chars with `0000`, and
  prefix `0-`, `1-`, etc. only as a duplicate counter for identical GUIDs.
  Prefer deriving the GUID from the Linux input modalias bus, VID, PID, and
  version fields, and when a display is already available prefer Ryubing's own
  `--no-gui --list-input-ids` output for the launch environment; Boomer's wired
  `057e:2009` reports `0-00000003-057e-0000-0920-000011810000` under Xwayland,
  not the displayless SDL probe's `...000000026803`. Include a non-null
  disabled `led` block or LED-capable SDL3 controllers crash during
  `SetConfiguration`.
  Keep `use_input_global_config = true` in the global config and mirror the
  managed input list into each launched title's `games/<titleid>/Config.json`
  because Ryubing can otherwise ignore global `input_config` during game
  launches. The stale `WindowKeyboard` profile with keyboard disabled
  leaves Switch games with no controls. Ryubing controller changes are not
  accepted by a timeout smoke alone: the generated `Config.json` must survive
  Ryubing startup, Ryubing logs must not report invalid configuration or "No
  matching controllers found" for connected players, and a live game must accept
  the connected Pro Controller profile, including L+R join where applicable.
  Do not change the Ryubing input schema from guessed field names; derive it
  from a known live-accepted profile or source and verify against the live log.
  Every `run-emulator` launch should keep the
  lightweight per-process Select+Start double-press exit broker; expanded
  standalone hotkeys stay opt-in per-emulator launch modes. Standalone emulator
  hotkey changes are accepted only after a live double-press test proves the
  broker is reading the real controller event node, targeting the current
  emulator PID or process group, logging the exit request, and closing the
  emulator. Boomer's managed
  ES-DE UI defaults are
  manufacturer/type/year systems sorting, visible clock, Switch Pro
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
  expanded standalone raw hotkey brokers must be opt-in per-emulator launch modes.
  Controller Maps should stay text-only with a compact two-column physical map
  above hotkeys, no ASCII controller art. Keep N64 A on physical Switch B and
  N64 B on physical Switch Y, and launch GZDoom with the managed Boomer
  controls cfg. Reset
  stale `Doom.Bindings` and automap sections so GZDoom regenerates its generic
  defaults, then override the current 8BitDo Ultimate 2C probe in
  `boomer-controls.cfg`: B/Joy1 jump, A/Joy2 use, X/Joy3 crouch, Y/Joy4 reload,
  L1/Joy6 User 1, R1/Joy7 User 2, L2/Joy8 alt-fire, Minus/Joy10 automap,
  Plus Joy11/Joy12 menu candidates, D-pad/POV1 left-right weapons and up-down
  inventory, R2 Joy9/Joy14/axis trigger fallbacks fire, and axis 3 pitch scale
  `0.25`. Keep L4/R4 documented as unproven and unmapped until a live probe
  shows unique events. Keep only the GZDoom menu A/B package patch unless a
  future live probe proves another package patch is required.
  After Burner Climax should launch through TeknoParrot XML profiles under
  `TeknoParrotUi.exe --profile`, not by direct native ELF execution; test on
  Boomer's active kiosk `DISPLAY=:0`, not only via SSH. TeknoParrotUi requires
  the `--profile` argument to name an existing official `GameProfiles/*.xml`
  file even when the launch profile itself is copied from ES-DE. The live
  After Burner Climax ROM folder was removed while TeknoParrot debugging is
  paused; the last blocker was `ElfLdr2/BudgieLoader.exe` exiting before
  spawning `abc` even though GE-Proton with Xalia disabled avoided Wine's
  loader stack crash.
  Boomer's probed kernel Switch Pro raw map is documented in
  `docs/boomer-kuwanger-emulation.md`.
  Bluetooth Settings controller counts should come from resolved player order,
  not only BlueZ connected devices, so wired controllers show up correctly;
  keep `joycond` installed but inactive unless live testing proves it is needed.
  Keep `/run/ghostship-emulation/controllers` writable by the kiosk user because
  `run-emulator` writes launch-time resolved controller append configs there.
  Dolphin 2603 loads hotkeys from `[Hotkeys]`, not `[Hotkeys1]`; keep
  broker-injected GameCube fallback bindings on Dolphin's
  `XInput2/0/Virtual core pointer` device and use Dolphin's grouped hotkey
  keys such as `General/Reset`, not `Keys/Reset`.
  WiiWare games should stay as extracted `.wad` files in the Wii ROM
  folder so ES-DE can launch them through Dolphin. Dolphin runtime config/cache
  can be reset, but preserve `/srv/emulation/xdg/share/dolphin-emu` because it
  contains save/NAND state.
  Ryubing firmware installs must use its native
  `bis/system/Contents/registered/<nca>.nca/00` layout; flat `.nca` files in
  `registered` are ignored by Ryubing's content scan.
  Ryubing `dlc.json` NCA paths must use PFS full paths with a leading `/`;
  bare `*.nca` child paths fail at runtime with `ResultFsPathNotFound`.
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

- Electron filters `BrowserWindow.getAllWindows/fromId` by constructor name.
  Keep wrapper classes named `BrowserWindow` or native state broadcasts omit them.

- Codex browser file pickers opened from an upstream modal must be mounted
  inside that modal. Stopping bubble-phase events is insufficient because the
  upstream outside-click handler observes document capture events; verify the
  physical folder-selection round trip in a real browser.
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
- On `chill-penguin`, RomM's live NAS library path is
  `/mnt/share/Library/ROMS/ROMS`; the old `/mnt/share/Library/ROMs` path can be
  absent.
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

- Validate Kuma provisioning with existing monitors: its login/stat burst exceeds
  Python Engine.IO's default 16-packet polling limit.
- Validate Seerr setup against the installed image's `/app/seerr-api.yml`;
  the released image's API can lag the development branch.
- Hermes and Firecrawl are retired from the `chill-penguin` self-hosted stack.
  Keep their modules, image contexts, secret sources, dashboard entries, and
  runtime projections removed; use the cleanup modules for stale live artifacts.
- Secret source bundles live under `secrets/files/sources/`; services should consume projected runtime env files from `/run/ghostship-secrets`, not source bundles directly.
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
- n8n on `chill-penguin` should stay as a single SQLite-backed service with state persisted under `/srv/apps/n8n`; keep browser access behind Cloudflare and expect a one-time manual Muximux reorder after deployment so the live tile sits directly under Bazarr.
- Chaptarr on `chill-penguin` should follow the standard arr service pattern: keep its config under `/srv/apps/chaptarr`, mount the shared downloads root at `/downloads`, mount `/mnt/share/Library/Books` plus `/mnt/share/Library/Audiobooks` as separate library roots, and source its API key from the `chaptarr` source projection. Grimmory should keep both library roots mounted because it is the primary consumption UI, and the generated Muximux dropdown order should place Chaptarr before Bazarr.
- Gluetun on `chill-penguin` should stay on Gluetun's custom-provider WireGuard path for PIA. `podman-gluetun` should start from the cached winner at `/srv/apps/gluetun/pia-wireguard-selection.json` or do only a provisional latency pick when no cache exists, regenerate `/run/secrets/gluetun-runtime.env` from that active winner during startup, and rely on `gluetun-pia-selector` to rerank Vancouver port-forward-capable WireGuard servers 5 minutes after boot and every 8 hours thereafter. The selector should pin Vancouver, benchmark the top 10 Vancouver servers with a bounded generic HTTPS download pull, and restart Gluetun only when a materially faster Vancouver winner is found while keeping PIA VPN-side port forwarding plus qBittorrent port reconciliation wired through Gluetun's native hooks and the generic `/v1/portforward` monitor path.
- qBittorrent 5.1.4 on `chill-penguin` can stay `disconnected` if it only binds to Gluetun by interface name (`tun0`). Reconcile `current_interface_address` to Gluetun's live `tun0` IPv4 as part of the Gluetun monitor or port-forward reconciliation, not just the interface name and listen port.
- Keep qBittorrent torrent data under `/downloads/Torrent` and incomplete data under `/downloads/Torrent/.incomplete`; do not let torrent `.parts` files land in the shared `/downloads` root.
- NZBGet on `chill-penguin` runs directly on `ghostship_net` at `http://nzbget:5001`; do not restore the retired Gluetun namespace compatibility proxy unless a current route requires it.
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
- Use source/provider/service bundles and catalog-driven projections instead
  of shared catch-all `HOMEPAGE_*` bundles or repeated raw secret path wiring.
- Keep self-hosted secret activation limited to `self-hosted-runtime` and
  `shared-runtime` catalog units; kiosk-owned emulation projections are rendered
  by `modules/emulation`.
- `bootstrap.sh` is the installer-time host bootstrap entrypoint. It captures a
  temporary intake bundle with `hardware-configuration.nix`, metadata, and the
  host SSH `ed25519` public key. WSL2 bootstrap must generate that host key if
  it is missing.
- `references/host-intake/<hostname>/` is temporary staging for Codex-assisted
  host integration. Remove it after Codex finishes integrating the host.
