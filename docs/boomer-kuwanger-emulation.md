# Boomer Kuwanger Emulation PC

`boomer-kuwanger` is managed as a dedicated NixOS emulation box through the
split `modules/emulation/` module set. The host boots the `kiosk` user directly
into ES-DE, keeps writable emulator state under `/srv/emulation`, and launches
every configured system through the repo-managed `boomer-run-emulator` wrapper.

## Runtime Layout

- `/srv/emulation/roms`: local ROM root. The future 4TB ROM SSD should mount
  here once the real disk UUID is known.
- `/srv/emulation/bios`: BIOS, firmware, keys, and other user-provided files.
- `/srv/emulation/saves`, `/srv/emulation/states`, `/srv/emulation/screenshots`:
  runtime output outside ROM folders.
- `/srv/emulation/config`: emulator overrides, display policy, RetroArch
  profiles, per-core options, controller state, and TeknoParrot prefix state.
- `/srv/emulation/es-de`: ES-DE appdata, settings, themes, custom systems, and
  scraped media.
- `/srv/emulation/logs`: launch, RetroArch, controller, and tool logs.
- `/home/kiosk/Emulation`: symlink to `/srv/emulation`.

The module intentionally does not declare a fake ROM disk mount. Set
`ghostship.emulation.romDisk.uuid` after bootstrapping the hardware to mount
the real SSD at `/srv/emulation/roms`.

## Frontend

ES-DE is mandatory; Pegasus is not used. The module installs ES-DE 3.4.1 from
the official AppImage package, sets `ESDE_APPDATA_DIR=/srv/emulation/es-de`,
installs Art Book Next, and generates:

- `/srv/emulation/es-de/custom_systems/es_systems.xml`
- `/srv/emulation/es-de/custom_systems/es_find_rules.xml`
- `/srv/emulation/es-de/settings/es_settings.xml`

`boomer-sync-esde-config` creates or refreshes the appdata skeleton at boot.
Additional setup scripts sync RetroArch, ES-DE tools, and standalone emulator
config scaffolds before the frontend starts. Existing ES-DE settings are
preserved after first creation so runtime UI changes can survive rebuilds.

## ROMs

The module maps every ROM folder discovered under `/mnt/z/Library/ROMs/roms`
into ES-DE. On boot, if a matching `/mnt/z` source folder is visible and
`/srv/emulation/roms/<folder>` is missing, the setup service creates a symlink.
Otherwise it creates an empty local folder for the future SSD.

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

`boomer-display-profile` detects the active resolution with Wayland/X11
fallbacks and computes output size, render size, aspect class, and FSR state.
`boomer-run-emulator` wraps emulator launches in Gamescope by default.

The default policy:

- Run ES-DE at native display resolution.
- Disable FSR for exact native output or clean low-resolution 2D cases.
- Enable Gamescope FSR for heavy 3D systems when render size is lower than the
  display target.
- Center fixed-aspect systems on ultrawide displays unless a native widescreen
  emulator mode is selected later.

Runtime override knobs can live in `/srv/emulation/config/display.env` for
manual testing, but durable policy changes belong in the Nix module.
Run `boomer-display-profile --matrix-test` to verify the deterministic FSR
policy without display hardware.

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
expensive or too stylized on target hardware. `boomer-retroarch-shader-smoke-test`
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

`boomer-controller-leds` watches connected devices and tries to apply player LED
state through sysfs. If a controller identity does not expose LED sysfs entries,
logical assignment still remains stable.

Wi-Fi is disabled at boot through NetworkManager/rfkill to prioritize Bluetooth
stability. Do not blacklist shared Wi-Fi/Bluetooth kernel modules until live
hardware confirms the adapter split.

## ES-DE Tools

The ES-DE Tools system exposes controller-friendly terminal menus for Wi-Fi,
Bluetooth, player assignment, display profile inspection, RetroArch
profile/shader switching, core status, scraper status, launch log review, ROM
coverage checks, restart, shutdown, and reboot. Tools edit runtime config under
`/srv/emulation/config` and do not mutate Nix-managed packages or RetroArch core
derivations.

## Scraping Secrets

The scraper secret unit is `emulation-scraper-secrets` with:

- `SCREENSCRAPER_USER`
- `SCREENSCRAPER_PASS`
- `THEGAMESDB_API_KEY`

The generated projection is:

```text
/run/ghostship-secrets/emulation-scraper.env
```

`secrets/recipients.nix` currently gives `emulation-runtime` to operator edit
keys only. Add `boomer-kuwanger`'s host SSH key after bootstrap, then rekey the
secret so the machine can decrypt it at runtime.

## Verification On Hardware

After SSH access exists:

1. Add the boomer host SSH key to `secrets/recipients.nix` and rekey
   `emulation-scraper-secrets`.
2. Add the real 4TB ROM SSD mount at `/srv/emulation/roms`.
3. Boot and confirm greetd lands in ES-DE with Art Book Next.
4. Pair all four controllers in Switch mode and verify connection-order player
   assignment.
5. Run `boomer-retroarch-shader-smoke-test`.
6. Launch one game per emulator family and inspect
   `/srv/emulation/logs/launches`.
7. Run `boomer-display-profile --matrix-test` and `boomer-rom-coverage-check`.
8. Test 1080p, 1440p, 4K, and ultrawide displays and refine Gamescope FSR
   thresholds if frame pacing misses budget.
