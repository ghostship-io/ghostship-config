# Specification: Refactor WSL-specific Home Manager Configuration

## Overview
Currently, `home/nixos.nix` contains logic specifically designed for WSL2 environments (notably the `ssh-agent` service with WSL-specific socket handling and the `wsl-open` alias). This track will extract these settings into a dedicated module to improve modularity and keep the main user configuration clean.

## Functional Requirements
1.  **Extract WSL Logic**: Move the following from `home/nixos.nix` to a new `home/wsl.nix`:
    - `services.ssh-agent` configuration (including the custom systemd service and post-start script).
    - `programs.fish.shellAliases.open = "wsl-open"`.
    - WSL-specific Fish initialization (specifically sourcing `.inshellisense/fish/init.fish` if it exists, as it's currently tied to the WSL workflow).
2.  **Conditional Activation**: Configure `home/nixos.nix` to automatically import `home/wsl.nix` only if `osConfig.wsl.enable` is true.
3.  **Cleanup**: Remove the redundant logic from `home/nixos.nix`.

## Non-Functional Requirements
- **Maintainability**: The separation of concerns will make it easier to add more WSL-specific tweaks without cluttering the base configuration.
- **Reproducibility**: Ensure that the `launch-octopus` host retains all current functionality.

## Acceptance Criteria
- `home/nixos.nix` contains no WSL-specific code blocks.
- `home/wsl.nix` exists and contains the extracted logic.
- Running `sudo nixos-rebuild build --flake .#launch-octopus` succeeds.
- On a WSL host, the `open` alias points to `wsl-open` and `ssh-agent` starts correctly with the environment variables set in `~/.config/ssh-agent.env`.

## Out of Scope
- Porting non-WSL features to separate files (this track is strictly for WSL home config refactoring).
- Modifying the system-level `modules/common/wsl.nix`.
