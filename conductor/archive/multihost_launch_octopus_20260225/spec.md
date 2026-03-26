# Track Specification: Multi-Host Support and 'launch-octopus' Configuration

## Overview
This track introduces formal multi-host support by refactoring shared modules to be more configurable and implementing the specific configuration for the `launch-octopus` host.

## Requirements
- **Configurable Automation**: Refactor `modules/common/automation.nix` to use a custom option (e.g., `myOptions.autoUpgrade.enable`) so hosts can control their own upgrade behavior.
- **Launch Octopus Host**:
    - Directory: `hosts/launch-octopus/`
    - Files: `default.nix`, `hardware-configuration.nix`
    - Hostname: `launch-octopus`
    - User: `owner` (with static UID/GID 1000)
- **Flake Update**: Expose `launch-octopus` in `flake.nix`.
- **Maintain Placeholder**: Keep `hosts/workstation` as a generic template/default.

## Success Criteria
- `nix flake check` passes (if environment allows).
- Both `workstation` and `launch-octopus` are buildable outputs in the flake.
- Automation can be enabled/disabled per host via a unified option.
