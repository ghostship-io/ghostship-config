# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- **Boomer PICO-8 ES-DE support**: Seed a small starter set of existing NAS
  PICO-8 carts into an empty ES-DE ROM folder and document the PICO-8 Switch
  controller map in the on-device Controller Maps TUI and generated policy.
  Use clean `.png` PICO-8 cart names for ES-DE scanning.
- **Boomer ES-DE gamelists**: Stop generating ES-DE gamelists from Nix; let
  ES-DE own gamelist creation and updates.
- **Boomer TeknoParrot launchers**: Use `.teknoparrot` launcher files in ES-DE
  and parse their first non-comment line as a raw argument string, matching the
  `.gzdoom` launcher style.
- **Boomer TeknoParrot ES-DE identity**: Show TeknoParrot as its own ES-DE
  system instead of reusing the generic Arcade theme label.
- **Boomer TeknoParrot theme**: Add TeknoParrot metadata, logo, and system
  artwork to the managed Art Book Next ES-DE theme so it does not render blank.
- **Boomer TeknoParrot polish**: Use Star Wars Trilogy Arcade artwork for the
  TeknoParrot system background, force ES-DE's custom systems order, and run
  native `.teknoparrot` payloads by absolute path so filenames with spaces
  launch correctly.
- **Boomer TeknoParrot native runtime**: Run local native `.teknoparrot`
  payloads through a 32-bit FHS compatibility runtime so After Burner Climax
  can find its Linux loader and legacy arcade dependencies on NixOS.
- **Boomer TeknoParrot artwork**: Apply Art Book Next's diagonal system-art
  mask to the TeknoParrot Star Wars artwork so it matches stock system panels.
- **Boomer controller probe documentation**: Document the live Switch Pro
  kernel event mapping from the Boomer raw input probe so emulator bindings can
  be based on observed `EV_KEY`/`EV_ABS` codes instead of inferred labels.
- **Boomer Xemu first-run setup**: Launch Xemu with the Nix-generated
  `xemu.toml` machine settings and disable Xemu's welcome wizard so Xbox games
  do not stop at the manual machine configuration prompt when the required BIOS
  and HDD files are present. Hide Xemu's menubar during gameplay, and have
  Xbox launchable images use the `.xiso` naming convention while redump
  backups stay outside ES-DE's `.iso` scan suffix.
- **Boomer emulation setup rendering**: Keep the generated GZDoom config
  Python heredoc flush-left so `emulation-setup.service` can complete during
  deployment.
- **Boomer GZDoom controller reset**: Reset GZDoom button bindings to the first
  Boomer named-alias baseline from `e0e6880` instead of the later raw `JoyN`
  table, while keeping the managed right-stick axis map and 25% vertical look
  scale. The baseline maps A/B to use/jump, X/Y to inventory use/map toggle,
  L/R to previous/next weapon, ZL/ZR to alt fire/fire, Plus to menu, Minus to
  pause, and the D-pad to inventory/map actions.
- **Boomer smoke-test kiosk restore**: Restore `greetd` instead of
  `getty@tty1` after root-run smoke tests on kiosk-mode hosts so Boomer returns
  to ES-DE instead of a console login prompt.
- **Boomer Switch Pro controller alignment**: Align generated controller maps
  and emulator policy around physical Switch Pro labels: Star/Home stays
  controller-local turbo, Select/Minus is the hotkey modifier, Select+X opens
  emulator quick menus where supported, Square/Capture opens native console
  Home only where explicitly configured, and unsupported Square/Capture actions
  are no-op. Make Select+Start double-press send SIGTERM to the emulator
  process group and escalate to SIGKILL after 5 seconds if it stays alive.
  Seed GZDoom's SDL
  `[Joy:JS:*]` axis map so the right stick uses yaw/pitch instead of the Linux
  defaults that can look at the ceiling or treat vertical stick motion as
  left/right turning, with reduced vertical look sensitivity.
- **WSL OpenCode server port**: Move the WSL `opencode-server` Home Manager
  user service to `127.0.0.1:4096` for Windows desktop attachment.
- **VueTorrent download paths**: Persist qBittorrent's default save path at
  `/downloads/Torrent`, keep incomplete torrent data under
  `/downloads/Torrent/.incomplete`, and create that directory before
  VueTorrent starts so partfiles do not land in the shared downloads root.
- **Hermes shutdown signal**: Switch the `chill-penguin` Hermes container stop
  signal to `SIGTERM` so s6-overlay handles host-driven shutdown cleanly.
- **Codex queue skill**: Added a shared `codex-queue` skill for long
  manual-review Codex CLI queues with JSONL sharding, tmux-backed worktrees,
  idle-worker monitoring, ledger validation, smoke testing, and merge-preflight
  support while preserving the rule that final item judgments stay manual.
- **Boomer ES-DE tools menu**: Replace the individual controller and Wi-Fi
  tools with large-font `Bluetooth Settings` and `Wi-Fi Settings` TUIs that
  support keyboard and controller input, Bluetooth pairing/audio routing,
  player assignment, Wi-Fi profile management, and the 2.4 GHz policy toggle
  while keeping lower-level helper scripts available outside the visible menu.
  Launch the TUIs through Xwayland `xterm` in the ES-DE Gamescope session and
  log launcher diagnostics under `/srv/emulation/logs/tools/`. Refine the
  settings TUIs to a dark two-column layout with scroll-safe action lists,
  right-pane hover status, a single Bluetooth toggle, and hidden BlueZ host
  discoverable/pairable fields while retaining the active scanning state. Limit
  the raw input-event reader to controller-like devices so keyboard arrow
  presses are not handled twice, keep status blocks on the Status action only,
  compact Bluetooth status for four controllers plus headphones, and allow
  keyboard player assignment with B/Esc cancel. Fix Bluetooth pairing scans to
  run a real 10-second BlueZ discovery and parse newly discovered devices from
  the live scan output, filter the pairing picker to unconnected controllers,
  audio devices, and Bluetooth peripherals, and show whether each candidate is
  already paired. Register the BlueZ pairing agent during the pair command
  itself, tolerate BlueZ pair/connect commands that report an error after the
  device has already paired or connected, add a `Show Paired` Bluetooth menu
  item, ignore Switch Pro IMU/analog-stick idle noise in the raw input reader,
  and update controller LEDs through the controller-specific sysfs LED
  directory with Switch-style player counts. Add a controller-only Switch Pro
  autoconnect service, a `Controller Maps` TUI, and route `Restart ES-DE`
  through a dedicated delayed system service so it does not kill its own
  frontend session before the restart is queued. Tune Boomer's MediaTek
  MT7921/MT7961 Bluetooth stack for four Switch Pro controllers by preferring
  BR/EDR mode, disabling Wi-Fi power save and MT7921e ASPM, keeping BlueZ and
  `hid-nintendo` detailed debug logging available on demand instead of during
  normal play, removing joycond/cemuhook from the active service set,
  rate-limiting controller autoconnect, re-checking live connected state before
  each host-initiated connect, minimizing
  sysfs LED writes, and logging controller HID health plus pairing diagnostics.
  Dynamically compact connected controller player slots so remaining controllers
  slide down when a middle player disconnects and the returning controller joins
  at the end. Trigger controller slot reconciliation from controller input add
  events and BlueZ connected-property changes with short delayed retries for
  HID LED readiness, merge USB Switch-Pro HID nodes so USB controllers share the
  same player assignment and LED path, track the 8BitDo `2dc8:301a` wired USB
  mode as an input-only player identity, avoid treating stale Bluetooth HID
  nodes as connected when BlueZ no longer reports them, and serialize LED/order
  writes to reduce transient wrong player LEDs. Keep one-shot LED applies from
  being start-limited during fast reconnect cycles. Coalesce
  BlueZ-triggered retries through the one-shot unit and avoid force-writing
  already-correct LED entries so hid-nintendo output reports are not flooded.
  Debounce BlueZ event bursts and update the background state marker from
  one-shot applies to prevent immediate duplicate LED rewrites. Restore
  Boomer's default boot path to the ES-DE kiosk session, make the ES-DE restart
  tool handle both greetd kiosk mode and console mode, and give `bluetoothd`
  plus system D-Bus conservative CPU scheduling weight boosts without enabling
  realtime scheduling or IRQ pinning. Disable Bluetooth `SNIFF` low-power link
  policy for connected Switch Pro controllers so multiplayer sessions favor
  input latency over controller battery life. Make controller reconciliation
  fail-soft when BlueZ D-Bus is slow, rate-limit Switch LED sysfs writes to a
  half-second cadence, and modestly boost system D-Bus scheduling for BlueZ
  control traffic. Bound startup `btmgmt` tuning calls so a busy Bluetooth
  adapter does not hold controller services for long. Add Switch-style hotkeys
  with Select+X as quick menu,
  Select/Minus as the hotkey modifier, Star/Home documented as the controller
  turbo button, a raw controller hotkey monitor for normal emulator exits,
  left-stick-as-D-pad overrides for D-pad-only RetroArch systems, text-only
  two-column Controller Maps for every Boomer system family, an N64 direct A/B
  remap, and managed GZDoom Switch-style controller bindings plus a patched
  GZDoom menu confirm/back mapping.
- **Boomer Dolphin defaults**: Seed Dolphin analytics opt-out, fullscreen
  Vulkan graphics, audio, and Switch Pro controller defaults so GameCube, Wii,
  and WiiWare launches do not block on first-run dialogs.
- **Boomer WiiWare ROM support**: Add `.wad` and `.WAD` to the managed Wii
  ES-DE extensions so extracted WiiWare titles launch through Dolphin.
- **Boomer ES-DE preferences**: Enforce ES-DE's manufacturer/hardware/release
  systems sorting, display clock, Switch Pro controller prompts, and
  all-controller menu input during frontend config sync. Set Boomer to Hawaii
  standard time and patch Art Book Next's clock format with ES-DE-supported
  hour/minute tokens so the clock renders the hour.
- **Boomer service log cleanup**: Disable BlueZ's unused CSIP plugin alongside
  BAP, keep `audio-route` pointed at PipeWire Pulse instead of autospawning
  PulseAudio, and start UPower under the kiosk boot target for WirePlumber.
- **PyLoad download directory**: Set PyLoad's app config default download
  folder to `/downloads/PyLoad` during container initialization while keeping
  the shared `/downloads` mount unchanged, and remove the image's
  `--storagedir /downloads` command-line override so PyLoad honors the managed
  app setting.
- **Self-hosted secrets**: Limit the self-hosted secret module to
  `self-hosted-runtime` units so host-specific emulation secrets stay managed
  by the emulation module.
- **Boomer FBNeo and Switch launch fixes**: Fixed the performance harness so
  FBNeo's harmless romset search misses no longer classify a successfully loaded
  game as `blocked-missing-runtime`, documented the OutRun shader fallback path,
  and made Ryubing `.nro` launches expose sibling homebrew `data/` assets plus
  existing Switch keys through Ryubing's runtime directories.

- **Boomer Kuwanger emulation PC**: Added a dedicated `modules/emulation`
  NixOS module, enabled it on `boomer-kuwanger`, and wired ES-DE with Art Book
  Next, RetroArch cores, bundled shader packs including Mega Bezel, Gamescope
  FSR launch wrappers, standalone emulator coverage, PICO-8 `requireFile`,
  TeknoParrot free prefix scaffolding, Bluetooth/controller services, Wi-Fi
  disable policy, ES-DE tools, and scraper secret catalog entries. Split the
  module into focused submodules and added ROM disk options, per-core RetroArch
  option/override generation, display matrix testing, richer ES-DE tool menus,
  controller-order persistence, shader fallback status, ROM coverage checks,
  and standalone emulator config scaffolds. Declared Boomer's final label-based
  disk layout with the OS disk mounted at `/` and the ROM disk mounted at
  `/srv/emulation/roms`. Enabled durable SSH with root key login only, disabled
  password and keyboard-interactive SSH authentication, and added Boomer's host
  SSH key to the emulation secret recipient group. Replaced the first-pass
  Wi-Fi rfkill service with a 5 GHz-only NetworkManager profile policy so Wi-Fi
  remains available while avoiding 2.4 GHz associations for Bluetooth. Switched
  Boomer's bootstrap startup mode to a tty shell with `kiosk` auto-login and a
  manual `start-esde` Gamescope/ES-DE launch action until hardware
  bring-up is stable. Hardened Boomer's Wi-Fi bootstrap service so it waits for
  NetworkManager, clears stale Wi-Fi interface pins, and explicitly brings up
  saved 5 GHz profiles when autoconnect does not fire on first boot. Disabled
  BlueZ's unused BAP/CSIP LE Audio plugins on Boomer so the Bluetooth daemon
  stops logging ISO-socket errors while keeping controller-oriented Bluetooth
  active.
  Reworked the controller monitor to read BlueZ devices over D-Bus instead of
  polling `bluetoothctl`, added ES-DE preflight/status helpers, cleared
  unexpected service capabilities so the ES-DE AppImage can run under Gamescope,
  and verified manual ES-DE launch/stop with console recovery on the HX100G.
  Renamed public emulation tools and services to drop the project prefix, made
  Gamescope display selection dynamic across connected HDMI/DP outputs, narrowed
  ES-DE scraper secret wiring to ScreenScraper, and added smoke ROM selection,
  sync, launch-test, and report helpers. Added PipeWire HDMI audio routing that
  selects the currently available AMD HDMI/DP profile, exposed an ES-DE Audio
  Status tool, tightened smoke-test fatal-log detection, and documented that
  only proven failing smoke copies should be manually extracted. Added a
  one-page Boomer hardware/software/system overview document.
  Realigned Boomer's default emulator map with RetroAchievements-friendly
  choices, moved PC Engine to Beetle SuperGrafx, NES/FDS to FCEUmm, PS2 to
  standalone PCSX2, PSP to standalone PPSSPP, and 3DS to Azahar where
  available. Removed Gamescope FSR entirely, keeping Gamescope only as the
  fullscreen/session wrapper, changed the RetroArch default shader policy from
  Mega Bezel to clean NNEDI3/sharp profiles, kept Mega Bezel selectable, and
  added a dedicated RetroAchievements secret projection plus RetroArch runtime
  credential renderer. Added a repeatable emulator performance harness with
  quick, overnight, shader-matrix, scaling-matrix, report, compare, and profile
  tools that reuse `run-emulator`, parse MangoHud CSV frame metrics, and write
  tuning recommendations without automatically mutating runtime profiles.
  Cleared transient smoke/perf test capability sets so `steam-run`/bubblewrap
  emulators launch without the unexpected-capabilities failure seen during
  PICO-8 testing, and classified PICO-8 performance tests as 30 FPS by default
  because many carts, including the `POOM.png` smoke cart, target that rate.
  Replaced nixpkgs' stable Ryubing package with a pinned official Ryubing
  Canary binary package and added `update-ryubing-canary` so the pin can be
  advanced from the official latest redirect before Boomer rebuilds. Added
  Batocera-style `.gzdoom` launcher support for the Doom system so ES-DE can
  list curated launch files while GZDoom receives the referenced WAD/PK3 assets,
  and aligned Boomer's ES-DE ROM folder names exactly with the source
  `/mnt/z/Library/ROMs/roms` library.
  Added `POOM.png` as the PICO-8 smoke cart and made PICO-8 launches request
  an explicit Gamescope Xwayland server so SDL can initialize on the TV path.
  Forced ES-DE's live theme setting to Art Book Next during setup and changed
  frontend-launched games to reuse the existing ES-DE Gamescope session instead
  of starting a nested Gamescope compositor.

- **OpenSpec removal**: Removed the managed OpenSpec wrapper, generated agent
  command surfaces, repo-local planning tree, and stale CLI cleanup path from
  develop-host agent tooling. Removed the installed global
  `using-git-worktrees` skill in favor of the maintained `merge-worktree`
  workflow.

- **Hermes 36841a0 env contract**: Updated the `chill-penguin` Hermes env
  wiring for upstream `ghostship-hermes` `36841a0`, restoring
  `GHOSTSHIP_CODEX_CHANNEL=1492841053642817606`, adding
  `DISCORD_WEBHOOK_CHANNEL=1491229248856260799`, and adding staged
  `hermes-secrets` keys for OpenCode Zen, ZenMux, and Electron Hub router
  providers.

- **VueTorrent errored-torrent auto-resume**: Added a managed timer that
  retries errored qBittorrent torrents every 5 minutes without a per-torrent
  retry cap. The retry action uses qBittorrent 5's
  `/api/v2/torrents/start` endpoint.

- **VueTorrent queue limits**: Set the managed qBittorrent queue to 5 active
  downloads, 20 active torrents, a 20 MB/s global download limit, slow torrents
  excluded from active queue limits, and post-completion rechecks enabled.

- **Hermes latest-image contract update**: Updated the `chill-penguin` Hermes
  contract for upstream `ghostship-hermes` `main` at `8a1a5cb`: Codex primary
  is now `openai-codex/gpt-5.5`, the managed web backend is Firecrawl, and
  Hermes receives the image-owned Bitwarden CLI appdata path plus new
  `hermes-secrets` stubs for Bitwarden, GitHub, and NVIDIA Build credentials.

- **WSL patched envfs restore**: Restored `services.envfs` on WSL hosts for
  Linux/FHS paths such as `/usr/bin/bash`, kept Windows PATH import for desktop
  interop, patched envfs to ignore Windows/DrvFS PATH binaries under
  `/usr/bin` even when WSL exposes them as `9p` mounts with `aname=drvfs`, and
  allowed metadata/path probes so shebang launchers such as npm and npx can
  reopen envfs-synthesized entries without WSL wrappers.

- **Merge worktree finish contract**: Updated the shared `merge-worktree` skill
  so its bundled finish helper fast-forwards local `main` without removing the
  source worktree, and clarified that agents should invoke the helper from the
  installed skill path under `$HOME/.agents/skills/merge-worktree`.

- **Firecrawl CloakBrowser loader fix**: Switched the Firecrawl Playwright sidecar patch to load the ESM-only `cloakbrowser` package through a small CommonJS helper, so the embedded CloakBrowser path works under the upstream service's current Node/TypeScript build output.

- **Firecrawl Postgres arm64 fix**: Replaced the broken `ghcr.io/firecrawl/nuq-postgres:latest` sidecar on `chill-penguin` with a repo-owned multi-arch `nuq-postgres` build based on `postgres:16`, preserving Firecrawl's upstream `nuq.sql` and `pg_cron` initialization so the `nuq` schema comes up correctly on arm64.

- **Standalone CloakBrowser manager removal**: Retired the old `cloakhq/cloakbrowser-manager` service, removed its manager-era Changedetection keepalive unit and timer, dropped the Homepage and Muximux manager tiles, and left Changedetection, PriceBuddy scraper, Firecrawl Playwright, and Hermes on their embedded or image-owned CloakBrowser paths only.

- **Homepage group rebalance**: Rebalanced only Homepage's `Services`, `Management`, `Utilities`, and `Infrastructure` columns while leaving the existing `Media`, `Automation`, and `Downloads` groups intact. `Services` now holds the day-to-day apps, `Management` holds dashboards plus control-plane tools like `n8n` and Changedetection, `Utilities` holds helper/search/conversion tools, and `Infrastructure` now focuses on backing caches, sidecars, and service databases including the Firecrawl Playwright/Postgres/RabbitMQ/Redis stack.

- **Firecrawl self-hosted stack**: Added a new internal-only Firecrawl stack on `chill-penguin` with the upstream API image, Redis, RabbitMQ, `nuq-postgres`, and a repo-owned Playwright sidecar image that patches Firecrawl in-place to launch CloakBrowser directly with `humanize=True`. Wired the new `firecrawl-secrets` bundle and `firecrawl-runtime` projection for `OPENAI_API_KEY`, `POSTGRES_PASSWORD`, and `BULL_AUTH_KEY`, reused the existing internal SearXNG instance at `http://searxng:8080`, projected `FIRECRAWL_URL` plus `FIRECRAWL_API_URL` into Hermes, and added Homepage plus Muximux visibility for `https://firecrawl.ghostship.io`.

- **Firecrawl public tile removal**: Removed the Homepage and Muximux links for `https://firecrawl.ghostship.io` and documented Firecrawl as an internal-only API service with no public web surface.

- **Homepage service regrouping**: Removed stale manager-era Homepage entries from the generated `Services` column, moved `SearXNG`, `BookStack`, `n8n`, and `Changedetection` into `Services`, moved `Firecrawl`, `Firecrawl Playwright`, and `PriceBuddy Scraper` into `Management`, kept `FlareSolverr` in `Utilities`, and pruned the old group placements from the generated `services.yaml`.

- **SearXNG Mojeek removal**: Removed `mojeek` from the enabled SearXNG engine set so the managed rendered config no longer includes it in the active Hermes-facing web pool.

- **Hermes Firecrawl API key projection**: Added a dedicated `FIRECRAWL_API_KEY` to the `firecrawl-secrets` bundle and projected it into Hermes' shared runtime env so Hermes can enable its Firecrawl client path while the internal Firecrawl server continues running without self-host DB auth.

- **Hermes Firecrawl env trim**: Removed the redundant `FIRECRAWL_URL` export from Hermes and kept only `FIRECRAWL_API_URL` for the internal Firecrawl integration contract.

- **Embedded CloakBrowser rollout**: Added repo-owned local image build contexts that embed CloakBrowser into `pricebuddy-scraper` and `changedetection`, replaced PriceBuddy's broken arm64 SeleniumBase sidecar with a repo-owned CloakBrowser Playwright service behind the existing `/api/article` contract, replaced changedetection's manager/CDP dependency with an in-image CloakBrowser Playwright path using `humanize=True`, and added a Firecrawl handoff document for the same binary contract.

- **SearXNG performance-first Hermes tuning**: Replaced the old broad allowlist with a much smaller Hermes-facing pool set, tightened SearXNG's global timeout budget, disabled image proxying, enabled a lightweight Hermes-safe limiter backed by the existing Valkey sidecar, added the persistent `/srv/apps/searxng-cache` bind mount for `/var/cache/searxng`, and replaced the old hand-maintained `settings.yml` mutation path with full managed rendering in `podman-searxng` `preStart` that now requires the existing `SEARXNG_SECRET_KEY` secret instead of generating a random key at startup. Live direct probes promoted `presearch` into the default web pool, while `brave` and `karmasearch` stayed out after immediate `429` and `403` responses.
- **Hermes SOUL persona refresh**: Replaced the default Hermes `SOUL.md` seed with the new Argo persona in the repo and on the live `chill-penguin` runtime so fresh seeds and the current host align on the same assistance and supervision contract.

- **WSL OpenCode desktop service**: Restored a repo-managed
  `opencode-server` Home Manager user service on WSL develop hosts so the
  Windows OpenCode desktop app can attach to `127.0.0.1:4096` over localhost
  forwarding, and removed the repo-managed `ghostship-paseo` daemon startup
  path.

- **Managed brainstorming skill**: Added the standalone
  `obra/superpowers/brainstorming` `skills.sh` install to the develop-host
  maintenance flow so `ghostship-agent-maintenance` keeps it installed and
  refreshed without expanding the repo-managed shared skill inventory.

- **Caveman and workflow retirement**: Removed the managed Caveman default
  behavior from develop hosts, replaced the old Codex Caveman injection with
  declarative cleanup of managed Caveman state, stopped maintenance from
  installing the Caveman Gemini extension or external `skills.sh` Caveman
  skill, and removed the obsolete shared `home/config/workflow.md` /
  `~/.agents/workflow.md` surface.

- **Shared agent instructions rewrite**: Replaced the old global agent prompt
  with the new concise Karpathy-style workflow guidance, removed the unused
  managed `~/.agents/AGENTS.md` target, rewired Codex, Gemini, and OpenCode to
  read directly from the canonical `home/config/AGENTS.md` source through their
  native instruction files, and taught WSL activation to publish the same file
  to the Windows-side Codex Desktop path `%USERPROFILE%\.codex\AGENTS.md`.

- **Hermes current-image runtime refresh**: Removed the stale downstream `CLOAKBROWSER_URL` export so Hermes follows the image-owned native CloakBrowser path, documented `/nix` first-boot seeding plus later default-profile reconciliation, and clarified that the next full Hermes reset must pull the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image, wipe persisted auth/XDG/custom-skill/workspace/user-Nix state, rely on bundled upstream default skill seeding, and require fresh Codex auth afterward.
- **Ragenix helper path fix**: Fixed `secrets/rules.nix` to emit rule keys relative to the rules file directory so `secret-edit <logical-id>` and other `ragenix` operations match the tracked `secrets/files/**/*.age` paths again.
- **Managed Paseo daemon and Node FHS wrappers**: Added `paseo` to the same wrapper-plus-maintenance flow used by the other agent CLIs, added a WSL-only `ghostship-paseo` system service that keeps a local daemon on `127.0.0.1:6768` for the Windows desktop app, documented Paseo's current daemon/app version-lockstep expectation, and replaced the broken raw WSL `/usr/bin/npm` plus `/usr/bin/npx` paths with explicit wrapper-backed WSL entries that exec the real Nix store binaries.
- **Develop web service removal**: Removed the managed `opencode-web` and
  `agent-deck-web` user services from the develop/WSL Home Manager profiles, so
  those localhost web daemons are no longer started declaratively on develop
  hosts.
- **Agent Deck maintenance alignment**: Moved `agent-deck` off the flake-pinned package path onto the same wrapper-plus-maintenance flow used by the other agent CLIs, so `ghostship-agent-maintenance` now rebuilds the latest upstream source release with the Ghostship web-mutations patch while the managed CLI remains available for manual use.
- **OpenCode Web UI service fix**: Switched the managed `opencode-web`
  user service to the Nix-provided Node binary instead of the nonexistent
  `/usr/bin/node`, restored an explicit `BROWSER` no-op target, and added
  no-op `xdg-open` plus `xdg-debug` shims so the headless service does not try
  to launch a browser while starting OpenCode. The managed service now runs
  `opencode serve` instead of `opencode web` and binds only to
  `127.0.0.1:4096`.
- **WSL explicit Windows interop contract**: Kept `services.envfs` on WSL hosts for Linux/FHS paths such as `/usr/bin/bash`, disabled automatic Windows PATH import so `envfs` stops synthesizing accidental Windows executables under `/usr/bin`, wrapped `wsl-open` around the real Windows PowerShell path, added a repo-managed `win-powershell` entrypoint, and updated WSL docs to require explicit wrappers or `/mnt/c/...` paths for Windows tools.
- **Dev shell export fix**: Reordered the default flake dev-shell packages to keep `git` before `age`, which avoids the current Nix `2.31.3` order-sensitive `get-env.sh failed to produce an environment` failure while preserving the existing tool set. Refresh `direnv` or start a new shell after pulling the change so the repaired environment export path is used.

- **Hermes default skill seed removal**: Stopped repo-managed default skill seeding for `chill-penguin` Hermes by removing the `skill-creator` copy-if-missing path from `podman-hermes` pre-start so the host now seeds only `SOUL.md` and leaves `/home/hermes/.hermes/skills/` entirely operator-managed by default.

- **Hermes Discord home export**: Added `DISCORD_HOME_CHANNEL=1491229269127598281` back to the `chill-penguin` Hermes container env as an explicit compatibility export while keeping the router/Codex lane contract and five-channel free-response list unchanged.

- **Hermes workstation `main` contract realignment**: Reworked `chill-penguin` Hermes host wiring around the current `ghostship-hermes` `main` image by dropping in-container `systemd` startup, removing host-side `/nix` bootstrap, moving the repo-managed `SOUL.md` and `skill-creator` defaults directly into `/srv/apps/hermes/home/.hermes/`, switching the Discord lane contract to `GHOSTSHIP_ROUTER_CHANNEL` plus `GHOSTSHIP_CODEX_CHANNEL`, rendering `DISCORD_FREE_RESPONSE_CHANNELS` with both pinned lanes and the current three Ghostship free-response channels, and documenting the required destructive stop-reset-start rollout for `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`.

- **Develop agent stack refresh**: Removed the repo-managed `launch-agent` helper, moved `openspec` onto the same managed auto-update path as `codex`, `gemini`, and `opencode`, made Caveman full the default agent style across Codex, Gemini, and OpenCode, and taught `ghostship-agent-maintenance` to ensure the configured `skills.sh` repos such as `JuliusBrussee/caveman` are installed and updated on each develop host.

- **Direct ragenix edit workflow**: Removed the repo-managed plaintext mirror
  helpers so operator secret changes now happen directly through
  `secret-edit <logical-id>`, with `secret-rekey` reserved for recipient
  changes.

- **Hermes pyLoad API contract**: Switched the Hermes utility env projection
  to follow the new upstream pyLoad contract by sourcing `PYLOAD_API_KEY`
  instead of `PYLOAD_USER` and `PYLOAD_PASS` from `pyload-secrets`.

- **BookStack documentation wiki**: Added a repo-managed BookStack service plus MariaDB sidecar to the `chill-penguin` self-hosted stack, wired the BookStack secret/env surface through the new `bookstack-secrets` bundle, exposed the service in Homepage's `Services` group, added a Muximux tile after Prowlarr, moved Chaptarr into the dropdown before Bazarr, and projected `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, plus `BOOKSTACK_TOKEN_SECRET` into Hermes through the managed runtime env path. The public `bookstack.ghostship.io` route and the initial in-app setup plus API token creation remain manual follow-up outside the repo-managed bootstrap path.
- **Ragenix secret catalog and host intake redesign**: Replaced `sops-nix` with `ragenix`, moved tracked secret storage to logical-unit `.age` files declared through `secrets/catalog.nix` and `secrets/recipients.nix`, added catalog-driven secret projections for shared consumers, restored the ignored `secrets.dec.yaml` plaintext mirror as the normal operator edit surface via `secrets-edit` plus `secrets-reencrypt`, and redesigned `bootstrap.sh` to capture temporary host-intake bundles with `hardware-configuration.nix` and SSH host `ed25519` keys for Codex-assisted integration.

- **Develop GitHub CLI ownership rollback**: Moved `gh` back to the shared
  develop Home Manager package set and removed the repo-managed WSL `envfs`
  fallback for `/usr/bin/gh` so the repo only promises GitHub CLI as
  develop-profile user tooling.

- **WSL FHS GitHub CLI compatibility**: Extended the WSL `services.envfs`
  fallback path so Windows-side tools such as Codex Desktop can resolve
  `/usr/bin/gh` even when the calling environment does not carry the develop
  profile PATH.

- **WSL FHS shell compatibility**: Enabled `services.envfs` on WSL hosts so
  hardcoded paths like `/usr/bin/bash` exist for Windows-side tools such as
  Codex Desktop when they target the NixOS guest.

- **Hermes single-agent cutover**: Replaced the old `assistant`/`operations`/`supervisor` runtime contract on `chill-penguin` with the upstream single-agent layout rooted at `/home/hermes/.hermes`, switched host wiring to the generic Discord and webhook env contract, stopped emitting any repo-managed browser CDP default, collapsed Hermes seeds to one root `skill-creator` tree plus one Crush Crawfish `SOUL.md`, limited managed CloakBrowser defaults to `Changedetection`, documented the required destructive reset of `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before first deployment, and aligned startup with the image-owned `ghostship-hermes-startup.service` plus `ghostship-hermes-user-tooling-refresh.timer` path.

- **Hermes Discord allowed users contract**: Switched the Hermes container env wiring from the retired per-profile `DISCORD_*_ALLOWED_USERS` inputs to the single upstream `DISCORD_ALLOWED_USERS` key so the exported Discord auth scope matches the current image contract.

- **Hermes HUD healthcheck**: Switched the Hermes container health probe to use in-container `curl` against `http://127.0.0.1:7681/` so the check follows the upstream HUD endpoint without embedding host-only Nix store paths that do not exist in the image-seeded `/nix`.

- **Develop agent-browser engine pin**: The managed `agent-browser` wrapper
  now defaults `AGENT_BROWSER_ENGINE=chrome` unless callers override it so
  local browser automation keeps using the profile-capable Chrome engine even
  when upstream auto-launch heuristics drift toward Lightpanda.

- **NZBGet UsenetPrime retirement**: Removed the unused `eu.usenetprime.com` backup server from the managed NZBGet config, dropped the retired `NZBGET_SERVER2_*` entries from the local plaintext secret mirror, and reconciled `chill-penguin` so live NZBGet state stops referencing the dead provider.

- **Develop OpenSpec telemetry opt-out**: The managed `openspec` wrapper now
  exports `DO_NOT_TRACK=1` and `OPENSPEC_TELEMETRY=0` by default so successful
  `openspec` commands stop printing harmless PostHog flush stack traces on
  hosts where telemetry egress is blocked.

- **Hermes pyLoad and n8n secret readiness**: Make Hermes wait for
  `pyload-secrets` and `n8n-secrets` before generating
  `/srv/apps/hermes/runtime.env`, and rerun the runtime env sync when either
  secret file changes so bundled utilities keep receiving the current pyLoad
  and n8n credentials.

- **Hermes utility env projection**: Reduced the Hermes container secret surface to `hermes-secrets` plus a generated `/srv/apps/hermes/runtime.env`, projected only the required utility-facing auth values from service-local secret or runtime files, added the missing internal utility URLs including Changedetection, Chaptarr, PriceBuddy, RSS-Bridge, and Synology, and now supply upstream with the generic single-agent Discord and webhook inputs it expects while leaving browser defaults unset so no repo-managed `BROWSER_CDP_URL` or `BROWSER_*_CDP_URL` values are emitted.

- **Synology NFS hard mounts**: Switched the managed Synology NFS mounts on
  `chill-penguin` and WSL hosts from `soft` to `hard` so transient server or
  network stalls stop surfacing as client-side I/O errors during file copies.

- **VueTorrent tunnel binding**: Reconciled qBittorrent's bound interface
  address to Gluetun's live `tun0` IPv4 in the Gluetun monitor, so qBittorrent
  stops getting stuck in a disconnected state after VPN restarts or namespace
  changes when binding by interface name alone is insufficient.

- **VueTorrent startup binding**: Prime `qBittorrent.conf` with Gluetun's live
  `tun0` IPv4 in `podman-vuetorrent` pre-start so qBittorrent no longer boots
  with the previous tunnel address and spends its first restart window unable
  to bind after Gluetun server changes.


- **Develop Gemini maintenance**: Removed the deprecated `experimental.plan` key from the generated develop-host Gemini system settings so managed Gemini launches stop warning about read-only stale config, and added `bash` to the maintenance runtime inputs so npm and npx subprocesses can spawn `sh` reliably during `ghostship-agent-maintenance`.

- **Develop Agent Deck maintenance and WSL web service**: Expose `agent-deck` through the repo-managed wrapper path, let `ghostship-agent-maintenance` refresh it from the latest upstream release, and keep the WSL-only `agent-deck-web` user service on `127.0.0.1:8420`.
- **Develop Workmux removal**: Removed the repo-managed `workmux` package and
  its known user-home artifacts from the supported develop-host workflow.
- **Develop Codex hook cleanup**: Extend the develop-host workmux cleanup to remove the stale `workmux set-window-status ...` commands from `~/.codex/hooks.json`, preserve unrelated valid hooks, warn on malformed hook JSON, and require a Codex or Agent Deck session restart after the relevant rebuild or switch if an old session was still holding the stale state.
- **OpenSpec Ghostship overrides**: `propose` now creates or reuses the change worktree before planning and ends
  with a detailed overview of the proposed change, `apply` now reports completed
  work, proposal updates, and issues found during apply, and `archive` now ends
  with suggested next issues or follow-up work after cleanup.

- fix(self-hosted): pin Gluetun to the live-benchmarked best PIA region, dynamically enumerate that region's current WireGuard servers at selector time, and only fall back to the global PF pool if the primary region disappears

- fix(self-hosted): use Gluetun's native container healthcheck, make Gluetun namespace dependents follow service restarts with `PartOf`/`Requires`, and switch VueTorrent to a local WebUI health probe instead of external `google.com`

### Changed
- **Develop Workmux packaging**: Added a repo-managed `workmux`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative tmux-first worktree orchestration
  without relying on the upstream installer or `cargo install`.
- **Hermes runtime contract**: Aligned the `chill-penguin` Hermes host module with the current single-agent `ghostship-hermes` contract by letting the image-owned startup service and mutable-tooling timer drive internal boot ordering, treating `/home/hermes/.hermes` as the authoritative managed runtime surface, and following the upstream-generated `TERMINAL_CWD=/workspace` root env contract.
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
- **Hermes root skill seeds**: Replaced the retired profile-local Hermes `skill-creator` seed copies with one root seed source under `modules/self-hosted/hermes-seeds/skills/skill-creator/`, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/skills/skill-creator/` only when that runtime-owned directory is missing while normalizing the copied tree to writable `apps:apps` ownership and permissions.
- **Gluetun PIA WireGuard selector**: Migrated `chill-penguin` Gluetun from native PIA OpenVPN to Gluetun's custom-provider WireGuard path, added a daily PF-capable PIA server selector that caches the preferred winner under `/srv/apps/gluetun/pia-wireguard-selection.json`, regenerated the runtime env at Gluetun startup, kept PIA VPN-side port forwarding on the persisted `/srv/apps/gluetun` state mount, and updated the monitor to use Gluetun's generic `/v1/portforward` control route while still reconciling qBittorrent/VueTorrent after startup and reconnects.
- **Gluetun selector fast-start benchmark flow**: Renamed the helper to a stable `gluetun-pia-selector` binary, changed `podman-gluetun` startup to trust the cached winner or do only a provisional latency pick, pinned selection to Vancouver, added a post-boot plus 8-hour background selector cycle, benchmarked the top 10 Vancouver port-forward-capable servers with bounded generic HTTPS pulls through temporary Gluetun tunnels, and only restart Gluetun when a challenger is materially faster than the current cached winner.
- **Hermes root SOUL seed**: Replaced the retired profile-local persona files with one root `modules/self-hosted/hermes-seeds/SOUL.md` source, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/SOUL.md` only when that runtime-owned file is missing so existing operator edits remain preserved after first seed.
- **Chaptarr book stack**: Added a repo-managed Chaptarr service to the `chill-penguin` arr stack with persisted config, shared `/downloads` access for both torrent and usenet flows, Homepage visibility, and declarative Muximux placement after Bazarr and before `n8n`. Grimmory now mounts both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` so it remains the first-class consumption surface for the shared library roots, while the public `chaptarr.ghostship.io` route stays part of the external Cloudflare/tunnel workflow.
- **Develop GitHub CLI baseline**: Added `gh` to the shared develop Home
  Manager package set so every develop-profile host gets the GitHub CLI by
  default.
- **Develop Agent Deck packaging**: Added a repo-managed `agent-deck`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative multi-agent orchestration tooling
  without using the upstream installer.
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
- **WSL `/mnt/z` activation reset**: WSL activation now stops the `/mnt/z`
  automount and unmounts any live NFS mount before reloading the generated
  mount units, so host switches do not fail on stale `/mnt/z` mount state.
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
