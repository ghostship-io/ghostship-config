# Boomer Kuwanger One-Page Overview

## Hardware

- Minisforum HX100G: Ryzen 7 7840HS, Radeon RX 6650M, Radeon 780M iGPU,
  32 GB RAM.
- OS disk: 512 GB NVMe, `BOOT` FAT32 at `/boot`, 32 GB swap, `nixos` Btrfs at
  `/`.
- ROM disk: 4 TB NVMe, `roms` Btrfs at `/srv/emulation/roms`.
- Display/audio target: HDMI/DP through the RX 6650M; PipeWire routes audio to
  the currently available AMD HDMI/DP profile.

## Software Stack

- NixOS host profile: `boomer-kuwanger`, console boot during bring-up.
- Frontend: ES-DE 3.4.1 AppImage, Art Book Next theme, Tools system enabled.
- Launch path: every game starts through `run-emulator`, which applies
  `display-profile`, Gamescope, optional Gamescope FSR, GameMode, MangoHud,
  HDMI audio routing, RetroArch profiles, and launch logging.
- Display policy: dynamic HDMI/DP connector discovery, 720p through 8K matrix,
  ultrawide pillarboxing for fixed-aspect systems, FSR only when render and
  output sizes differ.
- Runtime state: `/srv/emulation`; secrets projection:
  `/run/ghostship-secrets/emulation-scraper.env`.

## Systems And Emulators

| Library | Emulator/Core |
| --- | --- |
| Arcade - Final Burn Neo | RetroArch FBNeo |
| Arcade - TeknoParrot | TeknoParrot free via Wine prefix |
| Microsoft Xbox | xemu |
| NEC PC Engine / PC Engine CD | RetroArch Beetle PCE Fast |
| Game Boy / Game Boy Color | RetroArch Gambatte |
| Game Boy Advance | RetroArch mGBA |
| GameCube / Wii | Dolphin |
| Nintendo 3DS | Lime3DS if present, otherwise RetroArch Citra |
| Nintendo 64 | RetroArch Mupen64Plus-Next |
| Nintendo DS | RetroArch DeSmuME |
| NES | RetroArch Mesen |
| SNES | RetroArch Snes9x |
| Switch | Ryubing/Ryujinx-based |
| Virtual Boy | RetroArch Beetle VB |
| Wii U | Cemu |
| Neo Geo CD | RetroArch NeoCD |
| Neo Geo Pocket Color | RetroArch Beetle NeoPop |
| Dreamcast | RetroArch Flycast |
| Game Gear / Genesis / Master System / Sega CD | RetroArch Genesis Plus GX |
| Saturn | RetroArch Beetle Saturn |
| PlayStation | RetroArch Beetle PSX HW |
| PlayStation 2 | RetroArch PCSX2 |
| PSP | RetroArch PPSSPP |
| Sega Model 3 | Supermodel |
| Doom ports | GZDoom |
| PICO-8 | Official PICO-8 package via `requireFile` |

Installed RetroArch core set also includes MAME, SameBoy, bsnes, bsnes-hd,
PicoDrive, ParaLLEl N64, melonDS, and Citra where available.

## Controllers, Media, And Tests

- Controllers: four 8BitDo Ultimate 2C Bluetooth controllers in Switch mode,
  BlueZ with 5 GHz-only Wi-Fi policy, connection-order player assignment, and
  best-effort LED assignment.
- Scraping: ES-DE ScreenScraper credentials are rendered from secrets at
  runtime; credentials are not stored in the Nix store.
- Shaders: bundled Slang/GLSL/Cg shader packs installed, Mega Bezel default,
  clarity/performance fallbacks available.
- Current smoke status: 19/22 pass on hardware. Remaining blockers are missing
  BIOS files: Neo Geo CD BIOS, Saturn `mpr-17933.bin`, and PS1 `scph5500.bin`.
