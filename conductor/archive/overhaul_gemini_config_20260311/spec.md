# Specification: Overhaul Gemini Configuration & Module Refactor

## Overview
This track involves a structural refactor of the NixOS configuration and an overhaul of the Gemini CLI instructions. The `wsl` module will be renamed to `develop`, and the Gemini CLI system configuration will be relocated there. Additionally, the `system` skill will be converted into a global `gemini.md` file managed via Home Manager.

## Functional Requirements
- **Module Refactor**:
    - Rename `modules/wsl/` to `modules/develop/`.
    - Move `modules/common/gemini.nix` to `modules/develop/gemini.nix`.
    - Update all imports in `flake.nix` and host configurations to reflect the new `develop` module path.
- **Gemini Instruction Overhaul**:
    - Convert relevant core directives from `home/config/skills/system.md` into a new `gemini.md` format.
    - Focus on "remembering commands" and system-native workflows (nh, flakes, etc.).
    - Manage this `gemini.md` globally at `~/.gemini/gemini.md` using Home Manager (`home.file`).
- **Settings Management**:
    - Continue managing `settings.json` at the system level within the new `develop` module.
    - Update `settings.json` to remove the `system` skill from the default skills list.
- **Skill Removal**:
    - Delete `home/config/skills/system.md`.

## Acceptance Criteria
- [ ] Directory `modules/wsl/` is renamed to `modules/develop/`.
- [ ] Gemini system configuration is successfully moved to `modules/develop/gemini.nix`.
- [ ] `flake.nix` and host `default.nix` files are updated with new module imports.
- [ ] `~/.gemini/gemini.md` is correctly generated via Home Manager with distilled instructions.
- [ ] `settings.json` at `/etc/gemini-cli/settings.json` is updated and verified.
- [ ] The `system` skill is removed from the repository.
