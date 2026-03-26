# Specification: Add `dasel` and Configuration Merging Strategy

## Overview
This track involves adding `dasel` to the common system packages and implementing a NixOS-native mechanism to merge Nix-managed settings into configuration files that aren't fully managed by NixOS. This ensures that a "Source of Truth" from Nix is always applied while preserving other settings in the destination files.

## Functional Requirements
- **Add `dasel`**: Include `dasel` in `environment.systemPackages` in `modules/common/default.nix`.
- **Merge-on-Apply Strategy**:
    - Implement a NixOS activation script that executes on every `nixos-rebuild switch`.
    - The script uses `dasel` to merge Nix-defined values into target configuration files.
    - Only specific keys/paths defined in the Nix configuration should be overwritten or added to the target file; all other content must be preserved.
- **Configurable Targets**: (Optional/Future) Provide a way to easily define which files and keys to merge in the Nix configuration.

## Non-Functional Requirements
- **Reliability**: The merging process must not corrupt the target configuration files.
- **Idempotency**: The activation script should produce the same result every time it's run if the input Nix configuration hasn't changed.

## Acceptance Criteria
- [ ] `dasel` is available system-wide.
- [ ] A mechanism (activation script) is implemented to perform the merge.
- [ ] A test case (e.g., a sample config file) successfully demonstrates a merge of Nix-defined settings while preserving other content.
- [ ] `nix flake check` and `sudo nixos-rebuild switch` complete successfully.

## Out of Scope
- Migrating all existing unmanaged configurations to this new system at once.
- Handling complex binary configuration formats that `dasel` doesn't support.
