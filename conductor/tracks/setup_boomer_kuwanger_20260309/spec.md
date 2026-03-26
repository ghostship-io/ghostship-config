# Specification: Setup 'boomer-kuwanger' Emulation Host

## 1. Overview
Configure `boomer-kuwanger` (Minisforum HX100G) as a high-performance kiosk emulation PC using `cage`, `gamescope` (with FSR), and ES-DE on Wayland.

## 2. Target Environment
- **Host:** `boomer-kuwanger` (Ryzen 7 7840HS / Radeon 6650M).
- **User:** Dedicated `kiosk` user (UID/GID 1001).
- **Display Server:** `cage` launching `gamescope -f -e --fsr-upscaling 2 -- emulationstation`.

## 3. Recommended Core/Emulator Mapping (Mapped via cores.txt)

| System | Primary Emulator / Core | Notes from cores.txt / Research |
| :--- | :--- | :--- |
| **fbneo** | `FB Neo` | Arcade/Console/various |
| **mame** | `MAME (Current)` | Arcade/Console/various |
| **teknoparrot** | **Bottles** | Windows Arcade Loader |
| **nes** | `Mesen` | Nintendo NES/Famicom |
| **mastersystem** | `Genesis Plus GX` | Sega MS/GG/MD/CD |
| **pcengine** | `Beetle PCE FAST` | NEC PC Engine/CD |
| **megadrive** | `Genesis Plus GX` | Sega MS/GG/MD/CD |
| **pcenginecd** | `Beetle PCE FAST` | NEC PC Engine/CD |
| **snes** | `Snes9x` | Nintendo SNES/SFC |
| **neogeo** | `Geolith` / `FB Neo` | Geolith is highly accurate for Neo Geo AES/MVS |
| **segacd** | `Genesis Plus GX` | Sega MS/GG/MD/CD |
| **sega32x** | `PicoDrive` | Sega MS/GG/MD/CD/32X |
| **psx** | `Beetle PSX HW` | GPU-accelerated (OpenGL/Vulkan) |
| **neogeocd** | `NeoCD` | Neo Geo CD |
| **saturn** | `Beetle Saturn` | Sega Saturn |
| **virtualboy** | `Beetle VB` | Nintendo Virtual Boy |
| **n64** | `Mupen64Plus-Next` | Nintendo 64 |
| **dreamcast** | `Flycast` | Sega Dreamcast/NAOMI |
| **ps2** | `LRPS2` | Sony PlayStation 2 |
| **gamecube** | `Dolphin` | Nintendo GameCube/Wii |
| **xbox** | `DirectXbox` / `xemu` | xemu is generally preferred for Linux |
| **xbox360** | `Xenia` (Standalone) | Windows emulator via Wine/Proton |
| **wii** | `Dolphin` | Nintendo GameCube/Wii |
| **ps3** | `RPCS3` (Standalone) | Native Linux binary |
| **wiiu** | `Cemu` (Standalone) | Native Linux binary available |
| **switch** | `Ryubing` (Standalone) | User requested Switch fork |
| **gb** | `Gambatte` | Game Boy/Color |
| **gamegear** | `Genesis Plus GX` | Sega MS/GG/MD/CD |
| **gbc** | `Gambatte` | Game Boy/Color |
| **ngpc** | `Beetle NeoPop` | Neo Geo Pocket/Color |
| **gba** | `mGBA` | Game Boy Advance |
| **nds** | `melonDS DS` | Enhanced remake based on newer version |
| **psp** | `PPSSPP` | PlayStation Portable |
| **3ds** | `Citra` | Nintendo 3DS |
| **pico8** | **Native Binary** | Provided by user |
| **gzdoom** | `Native GZDoom` | PrBoom exists but native is preferred for GZDoom |

## 4. Hardware & Software Optimizations
- **Gamescope:** Force FSR upscaling for all emulators and the frontend. Use `gamescope -f -e --fsr-upscaling 2 -- emulationstation`.
- **Bluetooth:** `services.joycond` enabled for 4x 8BitDo Ultimate 2C in Switch Mode.
- **Network:** Disable 2.4GHz WiFi kernel module to prevent interference.
- **Kiosk:** `cage` compositor launching ES-DE via Gamescope for seamless, full-screen FSR.
- **RetroArch:** Use the `vulkan` video driver for best shader performance and latency.

## 5. Storage Layout (/home/kiosk)
To ensure portability and ease of backup, all user-specific data will be consolidated under `/home/kiosk`.

- **`/home/kiosk/Emulation/`**:
    - `roms/`: The root directory for all game media (managed via ES-DE standard).
        - `.../<system>/`: ROM files for each system.
    - `bios/`: System-specific BIOS/Firmware files (mapped in RetroArch `system_directory`).
    - `saves/`: Unified save game directory (`.srm` files).
    - `states/`: Unified save state directory (`.state` files).
    - `screenshots/`: Unified directory for all in-game captures.
- **`/home/kiosk/data/`**: Application data and configuration overrides.
    - `.../es-de/`: EmulationStation Desktop Edition data (managed via `ES_DE_HOME`).
    - `.../retroarch/`: RetroArch configuration, shaders, and core overrides.

## 6. Metadata & Scraping
- **RomM Integration:** Metadata will be sourced from the local **RomM** instance via its REST API where possible.
- **ES-DE Scraper:** Fallback to ES-DE's internal scraper (ScreenScraper/IGDB) for missing entries.
- **Media Storage:** All scraped media (covers, videos, manuals) will be stored in `/home/kiosk/data/es-de/downloaded_media/`.

## 8. Quality Shaders & Filters
To leverage the HX100G's power, the following high-quality shaders and filters will be used:

- **Primary CRT Shader:** **HSM Mega Bezel Reflection Shader** (Advanced presets).
- **Preset Pack:** **CyberLab Death to Pixels** (4K Optimized for crisp phosphor masks).
- **Per-System Presets:**
    - **8/16-bit:** Composite/S-Video style for authentic color bleed (e.g., CyberLab Composite Pure).
    - **32/64-bit & Handhelds:** PVM/BVM style for sharp, professional monitor look (e.g., CyberLab RGB PVM).
- **Video Filters:** **Blargg NTSC** filters for NES/Genesis to simulate authentic signal noise and transparency.

## 9. Acceptance Criteria
- [ ] System boots directly to ES-DE.
- [ ] 8BitDo controllers pair and function as Switch Pro Controllers.
- [ ] RetroArch configured with Vulkan and RetroAchievements.
- [ ] Kiosk user is restricted and optimized for gaming.
- [ ] **Storage:** All saves, screenshots, and BIOS files are correctly routed to `/home/kiosk/Emulation/`.
- [ ] **Metadata:** ES-DE correctly displays metadata and media for the library.
- [ ] **Visuals:** Mega Bezel + CyberLab shaders are active and performant on all 2D systems.
