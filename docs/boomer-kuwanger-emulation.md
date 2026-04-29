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
preserved after first creation so runtime UI changes can survive rebuilds.

During bootstrap, use:

- `esde-preflight` to check DRM, Vulkan, ES-DE appdata, and service
  readiness.
- `start-esde` to launch ES-DE under Gamescope on the RX 6650M and the
  currently connected HDMI/DP output.
- `esde-status` to inspect the active session and latest logs.
- `stop-esde` to return control to `getty@tty1`.

The ES-DE AppImage runs under bubblewrap, so the systemd session clears Linux
capabilities before launching Gamescope. Keep that service hardening in place
unless ES-DE is rebuilt from source.

## ROMs

The module maps every ROM folder discovered under `/mnt/z/Library/ROMs/roms`
into ES-DE. On boot, if a matching `/mnt/z` source folder is visible and
`/srv/emulation/roms/<folder>` is missing, the setup service creates a symlink.
Otherwise it creates an empty local folder, which should be hidden by the real
`roms` mount on the installed machine.

RetroArch is preferred when a usable libretro core exists. Standalone emulators
are installed where RetroArch is not the right target: Dolphin, Cemu, xemu,
Ryubing/Ryujinx, Supermodel, GZDoom, PICO-8, and TeknoParrot free.

## BIOS, Firmware, And Keys

Keep all proprietary runtime files out of the repo:

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

## Display And FSR

`display-profile` discovers connected DRM outputs first, prefers the RX 6650M,
supports either HDMI port, and falls back to Wayland/X11 resolution probes when
needed. It emits JSON with the selected connector, DRM card, output size,
render size, aspect class, FSR state, and Gamescope arguments. `run-emulator`
wraps emulator launches in Gamescope by default.

The default policy:

- Run ES-DE at native display resolution.
- Disable FSR for exact native output or clean low-resolution 2D cases.
- Enable Gamescope FSR for heavy 3D systems when render size is lower than the
  display target.
- Center fixed-aspect systems on ultrawide displays unless a native widescreen
  emulator mode is selected later.

Runtime override knobs can live in `/srv/emulation/config/display.env` for
manual testing, but durable policy changes belong in the Nix module.
Run `display-profile --matrix-test` to verify the deterministic FSR
policy without display hardware.

## Audio

Audio uses PipeWire with Pulse compatibility. `audio-route` runs from the
frontend session, emulator launcher, and user service to prefer the AMD
Navi 21/23 HDMI/DP audio card over USB audio adapters. It does not hardcode one
physical HDMI port; it asks PipeWire which AMD HDMI/DP profile is currently
`available`, sets that card profile, and makes the matching HDMI sink default.

Use the ES-DE `Audio Status` tool or run `audio-route` from SSH to inspect and
repair the route. The same tool can play a short test tone through the selected
HDMI sink.

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
mode prints the exact `run-emulator` calls without launching games.

The runtime launcher does not transform ROMs. If a smoke entry fails because
the selected copied entry is an archive or folder shape that the emulator will
not open, manually extract only that smoke copy and point `roms.json` at the
playable file. The final ROM set should already be stored in the launchable
shape expected by the target emulator.

## RetroArch

RetroArch is built with explicit cores for arcade, 8-bit, 16-bit, handheld,
PlayStation, Saturn, Dreamcast, N64, DS, PSP, PS2, and 3DS fallback coverage.
Managed config is written under `/srv/emulation/config/retroarch`.

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

Default shader profile is `megabezel-auto`. The installed runtime profiles are:

- `megabezel-auto`
- `megabezel-standard`
- `megabezel-potato`
- `megabezel-passthrough`
- `sharp-clean`
- `integer-raw`
- `performance`

Mega Bezel is the default because that was requested, but `sharp-clean` and
`integer-raw` are available for clarity-first tuning if Mega Bezel is too
expensive or too stylized on target hardware. `retroarch-shader-smoke-test`
writes `/srv/emulation/config/retroarch/shader-status.json`; the launcher uses
that marker to fall back from Mega Bezel to `sharp-clean` if the required shader
tree is missing.

## Controllers And Bluetooth

The first pass targets four 8BitDo Ultimate 2C Bluetooth controllers in Switch
mode. The host enables BlueZ experimental behavior, `hid-nintendo`, joycond
where available, Switch Pro/8BitDo udev access, and disables USB autosuspend
for the known controller identities.

Player assignment is connection-order based. Runtime state is stored at:

```text
/srv/emulation/config/controllers/player-order.json
```

`controller-leds` watches connected devices and tries to apply player LED
state through sysfs. If a controller identity does not expose LED sysfs entries,
logical assignment still remains stable.

Wi-Fi stays available for SSH, but NetworkManager Wi-Fi profiles are constrained
to 5 GHz to avoid 2.4 GHz contention with Bluetooth. Do not blacklist shared
Wi-Fi/Bluetooth kernel modules until live hardware confirms the adapter split.

## ES-DE Tools

The ES-DE Tools system exposes controller-friendly terminal menus for Wi-Fi,
Bluetooth, player assignment, display profile inspection, RetroArch
profile/shader switching, core status, scraper status, launch log review, ROM
coverage checks, restart, shutdown, and reboot. Tools edit runtime config under
`/srv/emulation/config` and do not mutate Nix-managed packages or RetroArch core
derivations.

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

## Verification On Hardware

After SSH access exists:

1. Verify `emulation-scraper-secrets` decrypts and projects ScreenScraper
   credentials.
2. Verify the label-based Btrfs mounts for `/` and
   `/srv/emulation/roms`.
3. Boot to the tty, run `esde-preflight`, then launch ES-DE with
   `start-esde` and confirm Art Book Next appears.
4. Run `audio-route` or the ES-DE `Audio Status` tool and confirm HDMI audio on
   each physical HDMI port you intend to use.
5. Pair all four controllers in Switch mode and verify connection-order player
   assignment.
6. Run `retroarch-shader-smoke-test`.
7. Launch one game per emulator family and inspect
   `/srv/emulation/logs/launches`.
8. Run `display-profile --matrix-test`, `rom-coverage-check`,
   `smoke-rom-select`, and `smoke-test --dry-run`.
9. Test 1080p, 1440p, 4K, and ultrawide displays and refine Gamescope FSR
   thresholds if frame pacing misses budget.
