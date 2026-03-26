# Track Specification: WSL-Specific Common Settings

## Overview
This track establishes a shared module for settings common to all WSL2 instances in the fleet, resolving platform-specific conflicts like the `systemd-resolved` warning.

## Requirements
- **WSL Common Module**: Create `modules/common/wsl.nix`.
- **DNS Conflict Resolution**: Disable `services.resolved` in the WSL common module to allow WSL to manage `/etc/resolv.conf`.
- **Host Integration**: Update `launch-octopus` to import `modules/common/wsl.nix`.
- **Guidelines**: Update `product-guidelines.md` to reflect the use of this module for WSL hosts.

## Success Criteria
- `launch-octopus` configuration evaluates without the `systemd-resolved` warning.
- Networking remains functional in WSL.
