# Specification: Nix Storage and Maintenance Optimization

## Overview
Automate the cleanup of old system generations and unused packages to maintain a "svelte" system and optimize disk space.

## Functional Requirements
- **Automated Garbage Collection**: Configure Nix to automatically delete unreachable store paths.
- **Generation Cleanup**: Automatically delete system generations older than 30 days.
- **Storage Optimization**: Ensure Nix automatically optimizes the store by hard-linking identical files (auto-optimise-store).
- **Schedule**: Set maintenance tasks to run weekly.

## Acceptance Criteria
- [ ] `nix.gc.automatic` is set to true.
- [ ] Garbage collection is scheduled weekly.
- [ ] Generations older than 30 days are automatically purged.
- [ ] `nix.settings.auto-optimise-store` is enabled.
- [ ] `nixos-rebuild switch` applies the configuration successfully.
