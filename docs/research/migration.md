# Migration Guide: `chill-penguin` (Mac Studio)

This guide provides the complete, step-by-step process for migrating your Mac Studio from its failing Asahi Linux installation to a fresh NixOS setup using this repository. It follows the official "UEFI Standalone" installation method.

---

## 1. Prerequisites & Backups
- [x] **Data Secured**: 23.95GB of databases, configs, and metadata pulled to `old/chill-penguin/`.
- [ ] **USB Drive**: Minimum 512MB (16GB+ recommended).
- [ ] **Internet**: Wi-Fi or Ethernet.

---

## 2. Software Preparation (Download Installer)
Standard NixOS ISOs won't boot on Apple Silicon. Download the latest pre-built bootstrap image:

1.  **Download the ISO**: [nixos-apple-silicon-release-2025-11-18.iso](https://github.com/nix-community/nixos-apple-silicon/releases/download/release-2025-11-18/nixos-25.11.20251112.c5ae371-apple-silicon-release-2025-11-18.iso)
2.  **Flash with Rufus (on Windows)**:
    *   **Device**: Your USB drive.
    *   **Boot selection**: Select the `.iso` file you just downloaded.
    *   **Partition scheme**: GPT.
    *   **Target system**: UEFI (non CSM).
    *   **START** to flash.

*(Note: Building from source via Nix is no longer recommended due to high resource requirements for cross-compilation. On M1 Ultra, you MUST build natively on the host or use a powerful remote builder).*

---

## 2.1. Special Kernel Requirements (M1 Ultra)
The Mac Studio M1 Ultra requires a specific kernel configuration to avoid black screens and boot loops:

1.  **Kernel Version**: Use **6.14.2-asahi**. Kernels 6.18+ currently break compatibility with older `m1n1` Device Trees (DTB), leading to "Synchronous Abort" crashes.
2.  **Rust Toolchain**: Pin to **Rust 1.84.0**. Kernel 6.14.2 uses new Rust features (`impl Trait + use<'_>`) that are not compatible with older 1.78.0 toolchains and require manual standard library source mapping in Nixpkgs.
3.  **Memory Addressing**:
    *   `ARM64_VA_BITS_48=yes`
    *   `ARM64_PA_BITS_48=yes`
    *   `NUMA=yes`
    *   `NODES_SHIFT=9`
    These are non-optional for M1 Ultra because Die 1 starts at an 80GB physical offset.
4.  **Compression**: Force `KERNEL_GZIP=yes`. Fedora's GRUB bootloader cannot decompress ZSTD kernels and will crash.
5.  **Alignment**: Build the `vmlinuz.efi` target and copy it to `$out/Image`. This ensures the 16K page alignment (`0x1000`) required by Apple's firmware.

---

## 3. UEFI Preparation (The Asahi Script)
Even for a reinstall, you must run the Asahi script from macOS to ensure the boot environment and peripheral firmware are correctly staged.

1.  Boot into **macOS** (if possible) or **macOS Recovery** (Hold Power button).
2.  Open Terminal and run:
    ```bash
    curl https://alx.sh | sh
    ```
3.  **Follow the Prompts**:
    *   **Resize**: Allocate the entire free space (or desired amount) for NixOS.
    *   **Install OS**: Select **"UEFI environment only"**.
    *   **Name**: Set the OS name to "NixOS".
4.  **Security Mode**: After the script finishes, shut down. Hold the Power button to enter the startup picker, select "NixOS", and follow the prompts to enter **Permissive Security** mode. This is required for m1n1 to boot custom kernels.

---

## 4. Boot the Installer & Connect
1.  Plug in your custom USB.
2.  Power on and select the USB drive in the U-Boot menu (if it doesn't auto-boot, use the `bootmenu` command).
3.  **Connect to Wi-Fi**:
    ```bash
    iwctl
    # Inside iwctl prompt:
    device list
    station wlan0 scan
    station wlan0 get-networks
    station wlan0 connect "YOUR_SSID"
    # Enter password and 'exit'
    ```
4.  **Verify**: `ping google.com`

---

## 5. Partitioning & Formatting (Manual)
> **WARNING**: Do NOT use automated partitioners. Do not touch partitions like `iBootSystemContainer` or `RecoveryOSContainer`.

1.  **Identify Partitions**: `lsblk` or `sgdisk -p /dev/nvme0n1`.
2.  **Create Root Partition**:
    Find the free space created by the Asahi script. 
    ```bash
    # Create partition (Type 8300 - Linux Filesystem)
    sgdisk -n 0:0:0 -t 0:8300 -c 0:"nixos" /dev/nvme0n1
    ```
3.  **Format Btrfs**:
    ```bash
    mkfs.btrfs -L nixos /dev/nvme0n1pX  # Replace pX with your new partition number
    ```
4.  **Create Subvolumes**:
    ```bash
    mount /dev/disk/by-label/nixos /mnt
    btrfs subvolume create /mnt/root
    btrfs subvolume create /mnt/home
    btrfs subvolume create /mnt/var
    umount /mnt
    ```

---

## 6. Mount & Install
1.  **Mount Hierarchy**:
    ```bash
    # Mount Root
    mount -o subvol=root,compress=zstd,noatime /dev/disk/by-label/nixos /mnt
    
    # Mount Subvolumes
    mkdir -p /mnt/{boot,home,var}
    mount -o subvol=home,compress=zstd,noatime /dev/disk/by-label/nixos /mnt/home
    mount -o subvol=var,compress=zstd,noatime /dev/disk/by-label/nixos /mnt/var
    
    # Mount EFI (Crucial: Use the partition UUID from the device tree)
    mount /dev/disk/by-partuuid/$(cat /proc/device-tree/chosen/asahi,efi-system-partition) /mnt/boot
    ```

2.  **Clone Repo**:
    ```bash
    mkdir -p /mnt/etc/nixos
    git clone https://github.com/ghostship-io/ghostship-config.git /mnt/etc/nixos
    cd /mnt/etc/nixos
    ```

3.  **Bootstrap**:
    ```bash
    ./bootstrap.sh chill-penguin
    ```
    *   **Action**: Note the Age public key and hardware config output.

4.  **Perform Installation**:
    ```bash
    nixos-install --flake .#chill-penguin
    ```

5.  **Finish**:
    ```bash
    umount -R /mnt
    reboot
    ```

---

## 7. Post-Migration (Restore)
Once booted into the new system:
1.  **Copy Data**: Transfer the 23GB backup to `/srv/apps/config`.
2.  **Restore DBs**: Replace service `.db` files with the backed-up versions.
3.  **Unpack Metadata**: 
    ```bash
    tar -xf plex_metadata.tar -C "/var/lib/plex/Library/Application Support/Plex Media Server"
    ```
4.  **Switch Config**: From a root shell, run `nixos-rebuild build --flake .#chill-penguin` and then `./result/bin/switch-to-configuration switch` to finalize the system state.
