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
  `display-profile`, Gamescope, GameMode, MangoHud,
  HDMI audio routing, the RetroArch global shader preset, and launch logging.
- Display policy: dynamic HDMI/DP connector discovery, 720p through 8K matrix,
  native render/output sizes, and centered pillarboxing for fixed-aspect
  systems on ultrawide displays. Gamescope FSR is disabled.
- Runtime state: `/srv/emulation`; secrets projection:
  `/run/ghostship-secrets/emulation-scraper.env` and
  `/run/ghostship-secrets/emulation-retroachievements.env`.

## Systems And Emulators

| Library | Emulator/Core |
| --- | --- |
| Arcade - Final Burn Neo | RetroArch FBNeo |
| Arcade - TeknoParrot | TeknoParrot free via Wine prefix |
| Microsoft Xbox | xemu |
| NEC PC Engine / PC Engine CD | RetroArch Beetle SuperGrafx |
| Game Boy / Game Boy Color | RetroArch Gambatte |
| Game Boy Advance | RetroArch mGBA |
| GameCube / Wii | Dolphin |
| Nintendo 3DS | Azahar if present, then Lime3DS, otherwise RetroArch Citra |
| Nintendo 64 | RetroArch Mupen64Plus-Next, GLideN64 3x native scaling |
| Nintendo DS | RetroArch DeSmuME |
| NES / FDS | RetroArch FCEUmm |
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
| PlayStation 2 | PCSX2 standalone |
| PSP | PPSSPP standalone |
| Sega Model 3 | Supermodel installed; ES-DE collection appears when the source library adds a matching folder |
| Doom ports | GZDoom |
| PICO-8 | Official PICO-8 package via `requireFile` |

Installed RetroArch fallback coverage also includes MAME, SameBoy, bsnes,
bsnes-hd, Beetle PCE Fast, Mesen, PicoDrive, ParaLLEl N64, melonDS, PPSSPP,
PCSX2, and Citra where available. ParaLLEl N64 stays installed as a fallback
core, but Boomer no longer generates managed ParaLLEl N64 runtime options.

## Controllers, Media, And Tests

- Controllers: four 8BitDo Ultimate 2C Bluetooth controllers in Switch mode,
  BlueZ with 5 GHz-only Wi-Fi policy, connection-order player assignment, and
  best-effort LED assignment.
- Scraping and achievements: ES-DE ScreenScraper and RetroAchievements
  credentials are rendered from dedicated secrets at runtime; credentials are
  not stored in the Nix store.
- Shaders: bundled Slang/GLSL/Cg shader packs installed, NNEDI3 clean scaling
  is the RetroArch default, and Mega Bezel remains selectable.
- Current smoke status: 19/22 pass on hardware. Remaining blockers are missing
  BIOS files: Neo Geo CD BIOS, Saturn `mpr-17933.bin`, and PS1 `scph5500.bin`.
