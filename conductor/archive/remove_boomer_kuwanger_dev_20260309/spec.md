# Specification: Remove boomer-kuwanger Dev Configuration

## Overview
This track focuses on the removal of all development-specific configurations for the `boomer-kuwanger` host. This includes deleting the dedicated development host directory and cleaning up any conditional logic or references within the main host configuration and the root `flake.nix`.

## Functional Requirements
- **Delete Development Host Directory**: Completely remove the `hosts/boomer-kuwanger-dev/` directory.
- **Cleanup Main Host Config**: Remove any conditional development-specific logic (e.g., Hyper-V or Gallium support) from `hosts/boomer-kuwanger/default.nix`.
- **Update Root Flake**: Remove the `boomer-kuwanger-dev` output from `flake.nix`.
- **Reference Integrity**: Ensure no other modules or files imports the deleted development configurations.

## Non-Functional Requirements
- **Maintainability**: Streamline the codebase by removing unused or redundant configurations.
- **Reproducibility**: Ensure that the remaining configurations still build reliably from scratch.

## Acceptance Criteria
- [ ] The `hosts/boomer-kuwanger-dev/` directory is deleted.
- [ ] `flake.nix` no longer contains a configuration for `boomer-kuwanger-dev`.
- [ ] `hosts/boomer-kuwanger/default.nix` is cleaned of dev-specific conditional logic.
- [ ] `nix flake check` (or equivalent build command) succeeds for all remaining hosts.

## Out of Scope
- Removal of any non-dev related configurations for `boomer-kuwanger`.
- Changes to the `launch-octopus` host.
