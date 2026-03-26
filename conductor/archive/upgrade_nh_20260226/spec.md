# Specification: Upgrade nh Helper to Latest Version

## Overview
Upgrade the `nh` (Nix Helper) utility to the latest version directly from its GitHub repository to fix the `nh search` 404 error and leverage the latest features.

## Functional Requirements
- **Flake Input**: Add the `nh` repository (`github:viperML/nh`) as a new input in `flake.nix`.
- **Package Replacement**: Update `environment.systemPackages` in `modules/common/default.nix` to use the `nh` package from the new flake input instead of the version in `nixpkgs`.
- **Standard Dependencies**: Allow `nh` to manage its own dependencies (standard flake behavior).

## Acceptance Criteria
- [ ] `nh --version` reports a version >= 3.7.0.
- [ ] `nh search <query>` returns valid results without a 404 error.
- [ ] System rebuild (`nh os switch .`) continues to work as expected.
- [ ] `nixos-rebuild switch` applies the configuration successfully.
