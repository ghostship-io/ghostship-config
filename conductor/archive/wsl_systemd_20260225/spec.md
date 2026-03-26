# Track Specification: Enable WSL2 Systemd Support

## Overview
This track configures the `launch-octopus` host to run correctly in a WSL2 environment with full `systemd` support, using the `nixos-wsl` module.

## Requirements
- **NixOS-WSL Input**: Add `github:nix-community/NixOS-WSL` to `flake.nix`.
- **WSL Module Integration**:
    - Import `wsl.nixosModules.wsl` into `launch-octopus`.
    - Set `wsl.enable = true`.
    - Set `wsl.defaultUser = "nixos"`.
- **Bootloader Cleanup**: Remove `boot.loader.systemd-boot` and `boot.loader.efi` from the host config as they are incompatible with WSL.
- **Hardware Config Cleanup**: Remove volatile WSL2 mounts from `hardware-configuration.nix`.

## Success Criteria
- `launch-octopus` configuration evaluates without errors.
- Systemd is enabled and managed via the `nixos-wsl` module logic.
