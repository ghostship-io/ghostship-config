# Track Specification: Configure Automated System Upgrades

## Overview
This track implements the automated, pull-based deployment strategy defined in the Tech Stack. It configures NixOS to automatically fetch updates from the project's Git repository and apply them to the system.

## Requirements
- **Automation Module**: A new NixOS module at `modules/common/automation.nix`.
- **system.autoUpgrade Configuration**:
    - `enable = true`
    - `flake = "git+ssh://git@github.com/ghostship-io/ghostship-config.git?ref=main"`
    - `dates` should be configurable (defaulting to a sensible daily schedule).
- **Integration**: Import the automation module into the `workstation` host configuration.

## Success Criteria
- The `workstation` configuration includes the `system.autoUpgrade` settings.
- The flake URL correctly points to `git@github.com:ghostship-io/ghostship-config.git`.
