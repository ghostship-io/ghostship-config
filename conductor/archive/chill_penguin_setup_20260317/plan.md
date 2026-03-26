# Implementation Plan: Fresh NixOS Installation on chill-penguin

## Phase 1: Build & Verify Official Installer [x] [checkpoint: b1d4e2a]

**Goal**: Build the official ARM64 NixOS installer from the `nixos-apple-silicon` repository and verify its integrity before flashing.

### Step 1.1: Build Default ISO [x]
- [x] Reset `old/nixos-apple-silicon` to `origin/main`.
- [x] Build the installer: `nix build .#installer-bootstrap -o installer -j4 -L`.
- [x] Verify the output `installer/iso/nixos-*.iso` exists.

### Step 1.2: Flash to USB [x]
- [x] Identify USB device using `lsblk`.
- [x] Flash ISO: `sudo dd if=installer/iso/nixos-*.iso of=/dev/sdX bs=4M status=progress oflag=sync`.
- [x] Sync and eject.

---

## Phase 2: Install NixOS on Mac Studio [x]

**Goal**: Boot the installer and perform the installation following the official guide.

### Step 2.1: Boot Installer [x]
- [x] Insert USB into Mac Studio.
- [x] Successfully reached the shell via U-Boot auto-boot.

### Step 2.2: Partition and Format [x]
- [x] Expanded partition 6 to fill the 3.6 TiB free space.
- [x] Formatted with **Btrfs** and created subvolumes: `@`, `@home`, `@nix`, `@log`.
- [x] Verified mount options: `compress=zstd`, `noatime`.

### Step 2.3: Install NixOS [x]
- [x] Performed `nixos-install` with optimized `hardware-configuration.nix`.
- [x] Set user passwords and successfully rebooted into the new system.

---

## Phase 3: Fleet Integration & Verification [x]

**Goal**: Manage chill-penguin via the main `nixos-config` repository.

### Step 3.1: Repository Migration [x]
- [x] Cloned `nixos-config` directly to `~/nixos-config` on the host.
- [x] Authorized `chill-penguin` in `.sops.yaml` and re-encrypted `secrets.yaml`.

### Step 3.2: Configuration Hardening [x]
- [x] Modularized development configurations to remove WSL dependencies.
- [x] Disabled root password system-wide in common modules.
- [x] Optimized host config for headless operation (disabled sound/firmware extraction).

### Step 3.3: Final Apply [x]
- [x] Final `nixos-rebuild switch` completed successfully.
- [x] Verified hardware health and system state.
