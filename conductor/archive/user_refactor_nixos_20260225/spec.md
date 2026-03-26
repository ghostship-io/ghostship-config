# Track Specification: Refactor Primary User to 'nixos'

## Overview
This track replaces the `owner` user with the default `nixos` user across the entire repository, ensuring consistent static UID/GID management for the new user.

## Requirements
- **User Migration**: Rename `home/owner.nix` to `home/nixos.nix`.
- **Identity Standards**: 
    - User: `nixos`
    - UID: `1000`
    - Group: `nixos`
    - GID: `1000`
- **Host Integration**: Update `hosts/launch-octopus/default.nix` to use the `nixos` user/group.
- **Flake Integration**: Update `flake.nix` to expose the `nixos` home configuration.
- **Documentation**: Update `conductor/product-guidelines.md`.

## Success Criteria
- The repository uses `nixos` as the primary user everywhere.
- `nixos` user has UID 1000 and GID 1000.
- `nix flake check` passes (if possible).
