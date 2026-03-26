# Specification: Fix NixOS Dynamic Executables with nix-ld

## Overview
NixOS cannot run dynamically linked executables intended for generic Linux environments out of the box. This prevents tools like VS Code Remote Server from running. Enabling `nix-ld` provides a compatibility layer.

## Functional Requirements
- Enable `programs.nix-ld.enable = true;` in the common NixOS configuration.
- (Optional) Provide a set of common libraries for `nix-ld` if needed for standard binaries.

## Acceptance Criteria
- [ ] `programs.nix-ld.enable` is set to `true` in `modules/common/default.nix`.
- [ ] System is rebuilt and `code .` (VS Code Server) can start.
