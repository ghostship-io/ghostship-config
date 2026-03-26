# Track chill_penguin_migration_20260317 Context

## Overview
Fresh NixOS installation on Mac Studio M1 Ultra using the official nixos-apple-silicon approach. This replaces the previous failing strategy that attempted to chainload from Fedora's GRUB.

## Documents

- [Specification](./spec.md) - Goals and architecture for the fresh installation
- [Implementation Plan](./plan.md) - 5-phase installation steps
- [Metadata](./metadata.json) - Track metadata

## Research (Legacy Debugging Knowledge)

Archived from previous failed attempts - **not needed for fresh install**:

- [Troubleshooting](../research/troubleshooting.md) - Boot failure logs, DTB mismatch analysis
- [Kernel Build Guide](../research/kernel-build-guide.md) - Custom kernel overlay documentation
- [Migration Guide](../research/migration.md) - Legacy migration guide
- [Background Builds](../research/background-builds.md) - Build procedure
- [Audit Report](../research/audit_report.md) - Hardware audit from original attempt

## Key Reference Documents

- [UEFI Standalone Guide](../../old/nixos-apple-silicon/docs/uefi-standalone.md) - Official installation guide with comprehensive troubleshooting
- [Release Notes](../../old/nixos-apple-silicon/docs/release-notes.md) - Version history and known issues

## Status Summary

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Pending | macOS Recovery & UEFI Preparation |
| 2 | Pending | Build & Analyze Installer on x86_64 (armored-armadillo) |
| 3 | Pending | Install NixOS on chill-penguin |
| 4 | Pending | Fleet Integration (add to flake.nix) |
| 5 | Pending | Post-Installation Verification |

## Phase 2 New Focus: ISO Analysis & Manual Boot

The new Phase 2 now includes critical analysis and backup preparation:

1. **Build the ISO** - Cross-compile ARM64 installer
2. **Analyze ISO structure** - Document kernel, initrd, DTB locations
3. **Extract rescue files** - Prepare manual boot fallback
4. **Document boot flow** - Understand the chain: m1n1 → boot.bin → GRUB → kernel

## Critical Architecture Notes

### m1n1 Stage 1 vs Stage 2

| Component | Location | Who Installs | Updates |
|-----------|----------|--------------|---------|
| **Stage 1 m1n1** | macOS stub partition | `curl https://alx.sh \| sh` | **Does NOT update automatically** |
| **boot.bin** | EFI `m1n1/boot.bin` | nixos-apple-silicon | Updated on every NixOS rebuild |
| **Kernel** | NixOS system | nixos-apple-silicon | Updated on every NixOS rebuild |

### Previous Failure Root Cause

The original approach chainloaded from Fedora's GRUB, which:
1. Used Fedora's `boot.bin` with Fedora's DTBs (for kernel 6.14.2)
2. Tried to boot NixOS with a different kernel (6.18+)
3. DTB mismatch → Synchronous Abort → black screen

The new approach uses nixos-apple-silicon's own `boot.bin` with matching DTBs.
