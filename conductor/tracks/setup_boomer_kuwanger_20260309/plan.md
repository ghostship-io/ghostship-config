# Implementation Plan: Setup 'boomer-kuwanger' Emulation Host

## Phase 1: System Foundation
- [ ] Task: Create `kiosk` user (UID 1001) and groups.
- [ ] Task: Configure `cage` and `gamescope` in NixOS modules.
- [ ] Task: Apply Bluetooth (MT7922) and 2.4GHz WiFi disable fixes.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: System Foundation' (Protocol in workflow.md)

## Phase 2: Controller & Input
- [ ] Task: Enable `services.joycond` and add 8BitDo udev rules.
- [ ] Task: Configure auto-pairing for the 4 controllers.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Controller & Input' (Protocol in workflow.md)

## Phase 3: Emulator & Frontend
- [ ] Task: Install RetroArch and the specific cores mapped in spec.md (Mesen, Snes9x, Genesis Plus GX, etc.).
- [ ] Task: Install Standalone emulators (Dolphin, PCSX2/LRPS2, Citra, Ryubing, RPCS3, Cemu, Xenia, xemu).
- [ ] Task: Set up **Bottles** and a dedicated prefix for TeknoParrot.
- [ ] Task: Install native binaries for PICO-8 and GZDoom.
- [ ] Task: Configure ES-DE with custom launch commands to use Gamescope with FSR for every system.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Emulator & Frontend' (Protocol in workflow.md)

## Phase 4: Storage & Metadata Integration
- [ ] Task: Implement the `/home/kiosk/Emulation` storage layout (roms, bios, saves, states, screenshots).
- [ ] Task: Configure `ES_DE_HOME` and system-specific paths in emulators (e.g., `system_directory`, `savefile_directory`).
- [ ] Task: Research and implement a basic script/tool to sync RomM metadata into ES-DE `gamelists`.
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Storage & Metadata Integration' (Protocol in workflow.md)

## Phase 5: Quality Shaders & Core Tuning
- [ ] Task: Install **Mega Bezel Reflection Shader** and **CyberLab Death to Pixels** shader pack.
- [ ] Task: Configure RetroArch to use `vulkan` and set up global shader defaults.
- [ ] Task: Implement per-system shader overrides (e.g., Composite for 8/16-bit, PVM for 32/64-bit).
- [ ] Task: Configure **Blargg NTSC** filters for core-level signal simulation.
- [ ] Task: Conductor - User Manual Verification 'Phase 5: Quality Shaders & Core Tuning' (Protocol in workflow.md)

## Phase 6: Final Validation
- [ ] Task: Perform cold boot and verify direct launch into ES-DE via Gamescope.
- [ ] Task: Verify 4x 8BitDo controller pairing and mapping in ES-DE and RetroArch.
- [ ] Task: Test sample ROMs for key systems and verify saves/screenshots go to the correct directories.
- [ ] Task: Verify metadata display in ES-DE.
- [ ] Task: Verify that shaders are active and performant (60 FPS) on high-end presets.
- [ ] Task: Conductor - User Manual Verification 'Phase 6: Final Validation' (Protocol in workflow.md)
