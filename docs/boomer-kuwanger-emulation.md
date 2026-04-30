# Boomer Kuwanger Emulation PC

`boomer-kuwanger` is managed as a dedicated NixOS emulation box through the
split `modules/emulation/` module set. During hardware bring-up, the host boots
the `kiosk` user to a tty and leaves ES-DE/Gamescope as a manual
`start-esde` action. It keeps writable emulator state under
`/srv/emulation` and launches every configured system through the repo-managed
`run-emulator` wrapper.

## Runtime Layout

- `/srv/emulation/roms`: local ROM root, mounted from the 4 TB Btrfs filesystem
  labeled `roms`.
- `/srv/emulation/bios`: BIOS, firmware, keys, and other user-provided files.
- `/srv/emulation/saves`, `/srv/emulation/states`, `/srv/emulation/screenshots`:
  runtime output outside ROM folders.
- `/srv/emulation/config`: emulator overrides, display policy, RetroArch
  profiles, per-core options, controller state, and TeknoParrot prefix state.
- `/srv/emulation/es-de`: ES-DE appdata, settings, themes, custom systems, and
  scraped media.
- `/srv/emulation/logs`: launch, RetroArch, controller, and tool logs.
- `/home/kiosk/Emulation`: symlink to `/srv/emulation`.

The Boomer host config uses label-based mounts. The emulation module's optional
`ghostship.emulation.romDisk.uuid` remains available for non-Boomer deployments,
but Boomer itself expects the installed disks to use the labels below.

## Disk Layout

`/dev/nvme0n1` is the 512 GB OS disk:

- `p1`: 1 GiB FAT32, label `BOOT`, mounted at `/boot`.
- `p2`: 32 GiB swap, label `swap`.
- `p3`: remaining space Btrfs, label `nixos`, mounted at `/`.

`/dev/nvme1n1` is the 4 TB ROM disk:

- `p1`: whole disk Btrfs, label `roms`, mounted at `/srv/emulation/roms`.

Btrfs mounts use `noatime`, `compress=zstd:1`, and `discard=async`. The ROM
mount intentionally avoids `autodefrag`.

## Frontend

ES-DE is mandatory; Pegasus is not used. The module installs ES-DE 3.4.1 from
the official AppImage package, sets `ESDE_APPDATA_DIR=/srv/emulation/es-de`,
installs Art Book Next, and generates:

- `/srv/emulation/es-de/custom_systems/es_systems.xml`
- `/srv/emulation/es-de/custom_systems/es_find_rules.xml`
- `/srv/emulation/es-de/settings/es_settings.xml`

`sync-esde-config` creates or refreshes the appdata skeleton at boot.
Additional setup scripts sync RetroArch, ES-DE tools, and standalone emulator
config scaffolds before the frontend starts. Existing ES-DE settings are
preserved after first creation so runtime UI changes can survive rebuilds,
except for managed defaults such as theme, systems sorting, display clock, and
controller UI hints. Boomer runs in Hawaii standard time and the managed Art
Book Next theme package formats the ES-DE clock as 12-hour time.

During bootstrap, use:

- `esde-preflight` to check DRM, Vulkan, ES-DE appdata, and service
  readiness.
- `start-esde` to launch ES-DE under Gamescope on the RX 6650M and the
  currently connected HDMI/DP output.
- `esde-status` to inspect the active session and latest logs.
- `stop-esde` to return control to `getty@tty1`.

ES-DE game launches reuse the frontend Gamescope session. Direct tty launches
still wrap emulators in DRM Gamescope, but nested Gamescope is skipped when
`DISPLAY` or `WAYLAND_DISPLAY` is already present.

The ES-DE AppImage runs under bubblewrap, so the systemd session clears Linux
capabilities before launching Gamescope. Keep that service hardening in place
unless ES-DE is rebuilt from source.

## ROMs

The module maps every ROM folder discovered under `/mnt/z/Library/ROMs/roms`
into ES-DE. On boot, if a matching `/mnt/z` source folder is visible and
`/srv/emulation/roms/<folder>` is missing, the setup service creates a symlink.
Otherwise it creates an empty local folder, which should be hidden by the real
`roms` mount on the installed machine.

RetroArch is preferred when a usable, RetroAchievements-compatible libretro
core exists. Standalone emulators are installed where they are the better
operational or RetroAchievements target: Dolphin, Cemu, xemu,
Ryubing/Ryujinx, Azahar, PCSX2, PPSSPP, Supermodel, GZDoom, PICO-8, and
TeknoParrot free.

Ryubing uses the official Canary Linux x64 release, not nixpkgs' stable
`ryubing` package. The current pin follows the official latest redirect at
`https://update.ryujinx.app/latest/canary` and is recorded in
`modules/emulation/ryubing-canary-pin.nix`. Run this before a Boomer rebuild to
advance the pin when upstream publishes a new Canary:

```sh
scripts/update-ryubing-canary /root/nixos-config
```

Nix still needs a fixed hash, so the build itself stays reproducible; the
updater is the intentional step that converts "latest Canary" into a Nix pin.
Switch homebrew `.nro` entries can keep their asset folders beside the launched
file. When `run-emulator` sees a sibling `data/` directory, it links that
directory into Ryubing's emulated SD card at
`/srv/emulation/xdg/config/Ryujinx/sdcard/data`, replacing only an existing
symlink. Proprietary keys stay operator-managed under
`/srv/emulation/bios/switch` and are exposed to Ryubing's runtime system
directory at launch.

## GZDoom

The Doom system uses the source library folder `Fantasy - GZDoom (2005)` in
ES-DE and accepts normal WAD/PK3 files plus Batocera-style `.gzdoom` launchers.
A `.gzdoom` launcher is a text file with one non-empty GZDoom argument line,
for example:

```text
-iwad assets/Doom II - Hell on Earth/DOOM2.WAD -file assets/SIGIL/SIGIL_v1_21.wad
```

`run-emulator` parses that line with shell-style quoting, does not execute it
through a shell, and launches GZDoom from the `.gzdoom` file's directory so
relative asset paths work. Keep assets under the Doom ROM folder and put the
human-facing launchers at the top level for cleaner ES-DE scraping.

## BIOS, Firmware, And Keys

Keep all proprietary runtime files out of the repo:

- Imported BIOS source mirror: `/srv/emulation/bios/systems`
- Switch firmware and keys: `/srv/emulation/bios/switch`
- PlayStation/PlayStation 2 BIOS: `/srv/emulation/bios`
- Sega CD, Saturn, Neo Geo CD, PC Engine CD BIOS: `/srv/emulation/bios`
- Xbox MCPX and HDD image material for xemu: `/srv/emulation/bios/xbox`

The Nix module only creates the directories and emulator launch contract.
Current smoke coverage has confirmed these BIOS-gated files are still needed
for the selected disc tests: `scph5500.bin` for Japanese PlayStation,
`mpr-17933.bin` for Saturn, and a valid Neo Geo CD BIOS set for NeoCD.

## PICO-8

The official PICO-8 zip is consumed with `pkgs.requireFile`:

- Expected source: `/mnt/c/Users/the owner/Downloads/pico-8_0.2.7_amd64.zip`
- Hash: `sha256-1alyii0bc9r9j2519q3jhxn8xazrcffy0kl8k07mnn208y2wxwpd`

The package wraps the Linux PICO-8 binary with `steam-run` so it can launch on
NixOS without committing proprietary files.

PICO-8 uses SDL's X11 video path on Boomer, so `run-emulator` adds an explicit
Gamescope Xwayland server for PICO-8 launches. Current smoke coverage uses
`POOM.p8.png` from the PICO-8 library as the heavier test cart.

## TeknoParrot Free

Only the free TeknoParrot path is scaffolded. No premium unlocks, bypasses,
commercial game files, or third-party patch packs are managed.

Place official free TeknoParrot files under:

```text
/srv/emulation/config/teknoparrot/TeknoParrot
```

The wrapper uses a dedicated Wine prefix at:

```text
/srv/emulation/config/teknoparrot/prefix
```

## Display And Aspect Scaling

`display-profile` discovers connected DRM outputs first, prefers the RX 6650M,
supports either HDMI port, and falls back to Wayland/X11 resolution probes when
needed. It emits JSON with the selected connector, DRM card, output size,
render size, aspect class, viewport recommendations, and Gamescope arguments.
`run-emulator` wraps emulator launches in Gamescope by default.

The default policy:

- Run ES-DE at native display resolution.
- Never use Gamescope FSR.
- Keep `render_width`/`render_height` equal to the active display output.
- Use emulator-native internal resolution scaling for standalone and 3D
  systems.
- Use RetroArch Slang shaders for clean 2D scaling.
- Center fixed-aspect systems on ultrawide displays unless a native widescreen
  emulator mode is selected later.

Runtime override knobs can live in `/srv/emulation/config/display.env` for
manual testing, but durable policy changes belong in the Nix module.
Run `display-profile --matrix-test` to verify native render/output sizing,
`fsr=false`, and aspect-safe viewport recommendations without display hardware.

## Audio

Audio uses PipeWire with Pulse compatibility. `audio-route` runs from the
frontend session, emulator launcher, and user service to prefer the AMD
Navi 21/23 HDMI/DP audio card over USB audio adapters. It does not hardcode one
physical HDMI port; it asks PipeWire which AMD HDMI/DP profile is currently
`available`, sets that card profile, and makes the matching HDMI sink default.
If `Bluetooth Settings` selects a connected Bluetooth audio sink, `audio-route`
honors that preference and falls back to HDMI when the Bluetooth sink is absent.

Run `audio-route` from SSH to inspect and repair the route.

## Smoke ROMs

Smoke ROM tooling lives under `/srv/emulation/smoke-roms` and
`/srv/emulation/config/smoke/roms.json`.

- `smoke-rom-select`: selects up to three top-level ROM entries per non-empty
  source system, preferring demanding known titles and otherwise choosing the
  largest entries.
- `smoke-rom-sync`: copies the selected entries into the smoke ROM tree.
- `smoke-test`: launches each selected entry through `run-emulator`, with
  Gamescope, GameMode, and MangoHud logging.
- `smoke-report`: summarizes the latest test run.

The smoke harness is intended for target-display validation. A `--dry-run`
mode prints the exact `run-emulator` calls without launching games. Root-run
smoke tests re-exec as `kiosk` on tty1 with cleared capability sets so
`steam-run`/bubblewrap-based emulators, including PICO-8, launch the same way
they do from ES-DE.

The runtime launcher does not transform ROMs. If a smoke entry fails because
the selected copied entry is an archive or folder shape that the emulator will
not open, manually extract only that smoke copy and point `roms.json` at the
playable file. The final ROM set should already be stored in the launchable
shape expected by the target emulator.

## Performance Testing

Performance tooling builds on the smoke ROM manifest and always launches
through `run-emulator`, so Gamescope, GameMode, HDMI audio routing, display
policy, RetroArch profile selection, and emulator logging follow the same path
as normal play. Gamescope FSR remains disabled for every run.

Runtime state:

- `/srv/emulation/config/perf/policy.json`: mode defaults, thresholds, shader
  profiles, scaling profiles, and tuning notes.
- `/srv/emulation/logs/perf/<run-id>/context.json`: package versions, kernel,
  display profile, audio summary, Vulkan summary, and mapped systems.
- `/srv/emulation/logs/perf/<run-id>/results.jsonl`: one JSON result per ROM
  and profile.
- `/srv/emulation/logs/perf/<run-id>/recommended-changes.json`: proposed
  tuning changes only; nothing is applied automatically.
- `/srv/emulation/logs/perf/<run-id>/mangohud/*.csv`: raw MangoHud frame data.

Commands:

- `perf-test --quick`: one ROM per mapped system, 75 seconds each with a
  15-second warmup.
- `perf-test --overnight`: up to three ROMs per mapped system, 180 seconds each
  with a 30-second warmup.
- `perf-test --shader-matrix`: RetroArch systems only, comparing default,
  `nnedi3-fast`, `nnedi3-clean`, `sharp-bilinear-prescale`, and `no-shader`.
- `perf-test --scaling-matrix`: standalone systems only, recording baseline,
  quality, and performance scaling profiles for emulator-native tuning.
- `perf-test --single <system> <rom>`: focused debug run for one ROM.
- `perf-report`: latest report table with average FPS, 1% low, p99 frame time,
  status, and recommendations.
- `perf-compare`: compares two runs and flags >3% FPS regressions or >2 ms p99
  frame-time regressions.
- Root-run performance tests use the same capability-cleared tty re-exec path
  as the smoke harness so fullscreen Gamescope launches match the production
  kiosk session.
- `perf-profile current`: shows the active RetroArch profile and current
  standalone runtime scaling policy files.

Use `--duration`, `--warmup`, and `--systems` for short validation loops, for
example:

```sh
perf-test --shader-matrix --systems nes,pcengine,gba,snes,fbneo --duration 12 --warmup 2
perf-test --scaling-matrix --systems psp,gc --duration 12 --warmup 2
```

Statuses distinguish launch failures from tuning failures. Missing BIOS,
firmware, keys, or proprietary emulator runtime files are reported as
`blocked-missing-runtime`; frame pacing failures are reported as
`fail-performance` with a recommendation such as lowering NNEDI3 quality,
falling back to sharp-bilinear, or lowering emulator-native internal
resolution. FBNeo logs many harmless `No romset found` search-path probes
before finding an arcade set; those probes are not treated as missing runtime
files once FBNeo reports a found romset or `No missing files, proceeding`.
For fast-scrolling FBNeo games such as OutRun, keep NNEDI3 as the default 2D
arcade policy and use per-content fallbacks in this order:
`nnedi3-balanced`, `nnedi3-fast`, `sharp-bilinear-prescale`, then `no-shader`.

## RetroArch

RetroArch is built with explicit cores for arcade, 8-bit, 16-bit, handheld,
PC Engine/SuperGrafx, PlayStation, Saturn, Dreamcast, N64, DS, PSP/PS2
fallback coverage, and 3DS fallback coverage. Managed config is written under
`/srv/emulation/config/retroarch`.

Default ES-DE mappings now use RetroAchievements-aligned cores where practical:

- NES/FDS: FCEUmm.
- PC Engine / PC Engine CD / SuperGrafx: Beetle SuperGrafx.
- GB/GBC: Gambatte.
- GBA: mGBA.
- SNES: Snes9x.
- N64: Mupen64Plus-Next.
- DS: DeSmuME.
- Dreamcast: Flycast.
- PlayStation: Beetle PSX HW.

Standalone defaults are PCSX2 for PS2, PPSSPP for PSP, Dolphin for GameCube
and Wii, and Azahar for 3DS when available.

Defaults:

- Vulkan video driver.
- PipeWire audio driver.
- Saves, states, screenshots, and logs outside ROM folders.
- Config save on exit disabled.
- Upstream joypad autoconfig installed when available.
- Per-core option files live under
  `/srv/emulation/config/retroarch/core-options`.
- Per-system override files live under
  `/srv/emulation/config/retroarch/system-overrides`.

## Shaders

The module packages current upstream RetroArch shader trees and exposes them in
RetroArch's expected layout:

- `shaders_slang`
- `shaders_slang/bezel/Mega_Bezel`
- `shaders_glsl`
- `shaders_cg`

Default shader profile is `nnedi3-clean`. The installed runtime profiles are:

- `nnedi3-clean`
- `nnedi3-quality`
- `nnedi3-balanced`
- `nnedi3-fast`
- `sharp-bilinear-prescale`
- `sharp-bilinear-simple`
- `pixel-aa-fast`
- `scalefx-aa-fast`
- `xbrz-freescale`
- `no-shader`
- `megabezel-auto`
- `megabezel-standard`
- `megabezel-potato`
- `megabezel-passthrough`
- `sharp-clean`
- `integer-raw`
- `performance`

NNEDI3 is used for clean 2D upscaling by default. Handheld systems use lighter
NNEDI3 where appropriate, 3D-heavy RetroArch systems default to no shader or a
light sharp-bilinear profile, and Mega Bezel remains installed and selectable
but is no longer the default. `retroarch-shader-smoke-test` writes
`/srv/emulation/config/retroarch/shader-status.json`; the launcher uses that
marker to fall back from missing NNEDI3/Mega Bezel paths to sharp or no-shader
profiles.

## Controllers And Bluetooth

The first pass targets four 8BitDo Ultimate 2C Bluetooth controllers in Switch
mode. The host enables BlueZ experimental behavior, `hid-nintendo`, joycond
where available, Switch Pro/8BitDo udev access, and disables USB autosuspend
for the known controller identities.

Player assignment is managed by the ES-DE `Bluetooth Settings` TUI. Runtime
state is stored at:

```text
/srv/emulation/config/controllers/player-order.json
```

`controller-leds` watches connected devices and tries to apply player LED state
through sysfs according to the saved player slots. If a controller identity does
not expose LED sysfs entries, logical assignment still remains stable.

Wi-Fi stays available for SSH, but NetworkManager Wi-Fi profiles are constrained
to 5 GHz by default to avoid 2.4 GHz contention with Bluetooth. The ES-DE
`Wi-Fi Settings` TUI can allow 2.4 GHz after showing a Bluetooth performance
warning. Do not blacklist shared Wi-Fi/Bluetooth kernel modules until live
hardware confirms the adapter split.

## ES-DE Tools

The ES-DE Tools system exposes large-font terminal TUIs for `Bluetooth Settings`
and `Wi-Fi Settings`, plus restart, reboot, and shutdown. The settings TUIs
support keyboard and controller navigation from the couch. Under the ES-DE
Gamescope session they launch through Xwayland `xterm`, with `foot` kept as a
pure Wayland fallback. Launch diagnostics are written under
`/srv/emulation/logs/tools/`. Helper scripts for audio, display, RetroArch,
scraping, launch logs, ROM coverage, smoke tests, and performance tests remain
available on disk for SSH or background use, but are not shown in the ES-DE
menu.

These tools are exposed as an ES-DE `Tools` system. Upstream ES-DE does not
provide a stable Batocera-style API for arbitrary native main-menu actions; that
would require a maintained ES-DE source build or patch.

## Scraping Secrets

The scraper secret unit is `emulation-scraper-secrets` with:

- `SCREENSCRAPER_USER`
- `SCREENSCRAPER_PASS`

The generated projection is:

```text
/run/ghostship-secrets/emulation-scraper.env
```

`secrets/recipients.nix` gives `emulation-runtime` to operator edit keys and
the Boomer host key. Rekey the secret after changing recipients so the machine
can decrypt it at runtime.

## RetroAchievements Secrets

The RetroAchievements secret unit is `emulation-retroachievements-secrets` with:

- `RETROACHIEVEMENTS_USER`
- `RETROACHIEVEMENTS_PASS`

The generated projection is:

```text
/run/ghostship-secrets/emulation-retroachievements.env
```

`render-retroachievements-settings` writes RetroArch's runtime
`cheevos_*` settings to:

```text
/srv/emulation/config/retroarch/retroachievements.cfg
```

RetroArch receives that file through `run-emulator` append config. Standalone
emulator achievement login remains `manual-login-required` until each live
config format is confirmed on Boomer; the status file records that deliberately
instead of guessing at credential keys.

## Verification On Hardware

After SSH access exists:

1. Verify `emulation-scraper-secrets` and
   `emulation-retroachievements-secrets` decrypt and project credentials.
2. Verify the label-based Btrfs mounts for `/` and
   `/srv/emulation/roms`.
3. Boot to the tty, run `esde-preflight`, then launch ES-DE with
   `start-esde` and confirm Art Book Next appears.
4. Run `audio-route` and confirm HDMI audio on each physical HDMI port you
   intend to use.
5. Pair all four controllers in Switch mode and verify connection-order player
   assignment.
6. Run `retroarch-shader-smoke-test`.
7. Launch one game per emulator family and inspect
   `/srv/emulation/logs/launches`.
8. Run `display-profile --matrix-test`, `rom-coverage-check`,
   `smoke-rom-select`, and `smoke-test --dry-run`.
9. Test 1080p, 1440p, 4K, and ultrawide displays and confirm fixed-aspect
   content stays centered and unstretched.
