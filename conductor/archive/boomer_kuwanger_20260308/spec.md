# Specification: Add boomer-kuwanger Host

## Overview
Add a new non-WSL2 host configuration named `boomer-kuwanger`. This host is intended for use as a dedicated emulator PC, initially supporting Wayland (Hyprland) and Mesa, with conditional hardware logic to support both a production AMD setup and a development Hyper-V (Gallium) environment.

## Functional Requirements
- **Host Structure**: Create `hosts/boomer-kuwanger/` with `default.nix` and `hardware-configuration.nix`.
- **System Configuration**:
    - Enable Wayland with **Hyprland** and **XWayland** support.
    - Configure **Mesa** for graphics acceleration.
    - Implement conditional logic in hardware configuration to toggle between **AMD** (production) and **Hyper-V/Gallium** (development/testing).
- **Module Integration**: Include all common, non-WSL modules:
    - `modules/common/default.nix` (Core settings)
    - `modules/common/users.nix` (User management)
    - `modules/common/secrets.nix` (SOPS integration)
    - `modules/common/gemini.nix` (AI tools)
    - `modules/common/automation.nix` (Automation tools)
- **Flake Integration**: Register the new host in the project's `flake.nix`.

## Non-Functional Requirements
- **Modularity**: Maintain strict separation between hardware-specific logic and shared system modules.
- **Reproducibility**: Ensure the host configuration is fully declarative and reproducible.

## Acceptance Criteria
1. The `boomer-kuwanger` host is correctly defined in `hosts/` and registered in `flake.nix`.
2. The configuration can be evaluated and built using Nix (e.g., `nix build .#nixosConfigurations.boomer-kuwanger.config.system.build.toplevel`).
3. Hyprland and XWayland are enabled in the resulting configuration.
4. Mesa drivers are correctly configured for both AMD and Gallium targets via a toggle or conditional check.

## Out of Scope
- Specific emulator software (RetroArch, etc.) installation and configuration (focused on the host OS environment).
- Physical deployment to hardware.
