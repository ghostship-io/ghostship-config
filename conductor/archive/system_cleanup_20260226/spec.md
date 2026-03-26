# Specification: Deep System Cleanup and Generation Pruning

## Overview
Perform an aggressive cleanup of the Nix store and system generations to free up disk space. This involves removing all old NixOS and Home Manager generations, keeping only the currently active ones, and running a thorough garbage collection.

## Functional Requirements
- **System Generation Pruning**: Remove all old NixOS system generations, retaining only the current one.
- **User Generation Pruning**: Remove all old Home Manager generations for the `nixos` user.
- **Aggressive Garbage Collection**: Run aggressive garbage collection to remove all unreferenced store paths.
- **Disk Space Verification**: Compare disk usage before and after the cleanup to quantify the space recovered.

## Acceptance Criteria
- [ ] Only the current NixOS system generation remains.
- [ ] Only the current Home Manager generation remains.
- [ ] Garbage collection has been successfully performed.
- [ ] A summary of space recovered is provided.