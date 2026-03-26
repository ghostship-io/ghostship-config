# Specification: Setup NixOS on chill-penguin (Mac Studio M1 Ultra)

## Overview
This track replaces the previous multi-attempt migration strategy with a clean, fresh installation using the official `nixos-apple-silicon` project. The Mac Studio will be reset to macOS, the Asahi Linux UEFI environment will be installed, and NixOS will be installed using a cross-compiled ARM64 installer built from an x86_64 host.

## Background: Why a Fresh Approach?

The previous strategy attempted to chainload NixOS from Fedora's existing GRUB, which caused persistent "Synchronous Abort" and black screen failures due to **DTB (Device Tree Blob) mismatch**.

### Understanding the m1n1 Architecture

Apple Silicon has a two-stage bootloader architecture:

**Stage 1 m1n1** (installed by `curl https://alx.sh | sh`):
- Written to the macOS stub partition (iBootSystemContainer)
- Acts as "firmware" - persists across OS updates
- Loads the Stage 2 payload (`boot.bin`) from the EFI partition

**Stage 2 Payload (`boot.bin`)** (created by nixos-apple-silicon):
- Stored in the EFI partition at `m1n1/boot.bin`
- Contains: m1n1 stage 2 + **DTBs** + compressed U-Boot
- **Updated when you rebuild your NixOS system**
- DTBs must match the kernel version

**The Problem**: When chainloading from Fedora's GRUB, you use Fedora's `boot.bin` with Fedora's DTBs. If NixOS uses a different kernel version (e.g., 6.18+ vs Fedora's 6.14.2), the DTBs don't match → Synchronous Abort.

**The Solution**: The `nixos-apple-silicon` installer builds its own `boot.bin` with DTBs from the **same kernel source**, ensuring they always match.

### What Gets Replaced vs What Persists

| Component | Installed By | Replaced When |
|-----------|-------------|---------------|
| Stage 1 m1n1 | `curl https://alx.sh \| sh` | Rarely (macOS stub partition) |
| boot.bin | nixos-apple-silicon | Every NixOS rebuild |
| U-Boot | nixos-apple-silicon | Updates |
| Kernel | nixos-apple-silicon | Updates |
| GRUB/systemd-boot | nixos-apple-silicon | Updates |

The new approach uses the official `nixos-apple-silicon` installer which:
1. Uses the existing Stage 1 m1n1 from the Asahi installer
2. Creates a new `boot.bin` with DTBs matching the NixOS kernel
3. Installs its own GRUB/systemd-boot to the NixOS EFI partition

## Functional Requirements

1. **macOS Recovery**: Restore macOS on chill-penguin using Apple Configurator or Recovery Mode
2. **UEFI Preparation**: Install Asahi Linux UEFI environment (m1n1 + U-Boot) via `curl https://alx.sh | sh`
3. **Installer Build**: Cross-compile ARM64 NixOS installer on `armored-armadillo` (x86_64)
4. **NixOS Installation**: Boot installer from USB, partition NVMe, install NixOS
5. **Fleet Integration**: Add chill-penguin to the nixos-config flake as a properly managed host

## Installation Architecture

```
Cross-compile on x86_64 (armored-armadillo):
  nixos-apple-silicon/.#installer-bootstrap
  → ARM64 ISO with:
    - Linux kernel (6.19.x from asahi-6.19.9-2)
    - GRUB EFI bootloader
    - initrd
    - nix-daemon

Install on Mac Studio M1 Ultra:
  1. macOS Recovery → reinstall clean macOS
  2. curl https://alx.sh | sh → installs m1n1 + U-Boot to EFI
  3. Boot USB installer → U-Boot → GRUB → NixOS installer
  4. Partition /dev/nvme0n1pX (Linux filesystem)
  5. nixos-install
  6. Reboot → NixOS
```

## Non-Functional Requirements

- **Reliability**: Use the officially supported installation path from nixos-apple-silicon
- **Simplicity**: No custom kernel overlays or version pinning workarounds
- **Reproducibility**: Cross-compiled installer is bit-for-bit reproducible
- **Maintainability**: Use official nixos-apple-silicon modules for kernel/boot updates

## Acceptance Criteria

- [ ] chill-penguin boots NixOS from its own EFI partition (not chainloaded)
- [ ] SSH access works on local network
- [ ] Basic system configuration (user, networking, sudo) is applied via flake
- [ ] chill-penguin is added to nixos-config flake.nix with proper imports
- [ ] Documentation of the process is complete in this track directory

## Out of Scope

- Migrating data from the old Fedora installation
- Setting up a desktop environment (headless server only)
- Restoring Docker containers or services from old install
- GPU acceleration testing (headless mode)

## References

- [nixos-apple-silicon GitHub](https://github.com/nix-community/nixos-apple-silicon)
- [Asahi Linux Installation Guide](https://github.com/nix-community/nixos-apple-silicon/blob/main/docs/uefi-standalone.md)
- [Asahi Linux Wiki](https://github.com/AsahiLinux/docs/wiki)
