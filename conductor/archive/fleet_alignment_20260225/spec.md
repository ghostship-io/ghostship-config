# Track Specification: Multi-Platform Fleet Alignment

## Overview
This track updates the project's core guidelines and repository logic to officially support a heterogeneous fleet consisting of WSL2 instances and bare-metal hardware (specifically a Mac Studio), without creating placeholder host configurations.

## Requirements
- **Guideline Update**: Update `conductor/product-guidelines.md` to define the architectural approach for mixed-platform support.
- **Platform Separation**: Ensure `modules/common/` contains only settings applicable to all platforms.
- **Architectural Flexibility**: Confirm `flake.nix` and module imports support varying architectures and boot processes (e.g., WSL systemd vs. Bare Metal EFI).

## Success Criteria
- Product Guidelines clearly explain how to add new WSL or hardware hosts.
- Shared modules do not contain WSL-specific or Hardware-specific "hacks".
- No new host placeholders are created.
