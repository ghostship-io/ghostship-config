# Hardware Audit Report: chill-penguin (Mac Studio)

> **STATUS**: This audit is from the **original Fedora installation**. For the fresh NixOS install, this information is **outdated** but kept as reference for disk partitioning decisions.
>
> **Action Required**: After reinstalling macOS and running `curl https://alx.sh | sh`, a **new audit should be performed** to capture the fresh partition layout.

## Original System Overview (From Fedora)
- **Host**: chill-penguin
- **Model**: Mac Studio (Apple Silicon, M1 Max/Ultra - `mac13j`)
- **Original OS**: Fedora Linux Asahi Remix 42
- **Original Kernel**: `6.14.2-401.asahi.fc42.aarch64+16k`
- **Architecture**: aarch64 (16k page size)

---

## Disk Layout Reference

This was the original partition layout from the Fedora installation. A **fresh install will start fresh** after macOS Recovery + `alx.sh`.

### Original Partition Layout
```
/dev/nvme0n1p1: Apple Silicon boot (500M)      - DO NOT TOUCH
/dev/nvme0n1p2: Apple APFS (76.8G)             - macOS container
/dev/nvme0n1p3: EFI System (477M)             - Old backup EFI (may differ after fresh install)
/dev/nvme0n1p4: Apple APFS (2.3G)             - RecoveryOS
/dev/nvme0n1p5: EFI System (500M)             - **Active EFI** (contains m1n1, U-Boot)
/dev/nvme0n1p6: Linux filesystem (1G)        - Old /boot (ext4) - will be recreated
/dev/nvme0n1p7: Linux filesystem (3.6T)       - Old root & home (Btrfs) - will be recreated
/dev/nvme0n1p8: Apple Silicon recovery (5G)   - DO NOT TOUCH
```

### Expected Fresh Partition Layout (After `alx.sh`)
```
/dev/nvme0n1p1: iBootSystemContainer           - macOS stub (500M) - DO NOT TOUCH
/dev/nvme0n1p2: Apple APFS Container         - macOS (resized)
/dev/nvme0n1p3: Apple APFS                   - Old Recovery (may be removed)
/dev/nvme0n1p4: EFI System (500M)            - **New EFI for NixOS**
/dev/nvme0n1p5: Linux Filesystem             - **NixOS root** (free space created by alx.sh)
/dev/nvme0n1p6: Apple Silicon Recovery       - DO NOT TOUCH
```

### Key Partition Notes
- **EFI partition**: After `alx.sh`, there should be a new EFI partition. The exact device depends on where free space was created.
- **Root partition**: Will be created in free space during NixOS installation.
- **The NixOS EFI partition must be separate** from macOS EFI - each OS needs its own.

---

## Boot Configuration Reference (Original)

- **Original Bootloader**: m1n1 -> U-Boot -> GRUB
- **Original EFI Mount**: `/dev/nvme0n1p5` mounted at `/boot/efi`
- **Original Boot Cmdline**: `BOOT_IMAGE=(hd0,gpt6)/vmlinuz-6.14.2-401.asahi.fc42.aarch64+16k root=UUID=72bd8b6f-0e7f-46f2-a181-6560211eabe7 rootflags=subvol=root`

---

## Driver Modules Reference (Original Fedora -> NixOS Mapping)

| Fedora Module | Function | NixOS Equivalent |
|---------------|----------|------------------|
| `asahi` | GPU / Mainline | `hardware.asahi.enable = true` |
| `nvme_apple` | SSD Controller | `boot.initrd.availableKernelModules = [ "nvme_apple" ]` |
| `apple_dart` | IOMMU | `boot.initrd.availableKernelModules = [ "apple-dart" ]` |
| `apple_dcp` | Display | Handled by `hardware.asahi` |
| `snd_soc_apple_mca` | Audio | `hardware.asahi.setupAsahiSound = true` |
| `pinctrl_apple_gpio` | GPIO | `boot.initrd.availableKernelModules = [ "pinctrl-apple-gpio" ]` |
| `spi_apple` | SPI | `boot.initrd.availableKernelModules = [ "spi-apple" ]` |
| `phy_apple_atc` | USB PHY | `boot.initrd.availableKernelModules = [ "phy-apple-atc" ]` |
| `macsmc` | SMC | `boot.initrd.availableKernelModules = [ "macsmc", "macsmc-power" ]` |

---

## Firmware Reference (Original)

These firmware files were in `/boot/efi/asahi/` on the original Fedora install. A **fresh NixOS install will need to extract these from the new EFI partition** after running `alx.sh`.

### Original Firmware Files
- `all_firmware.tar.gz` (28.9M): Peripheral firmware bundle (WiFi, BT, etc.)
- `kernelcache.release.mac13j` (25.8M): Apple boot firmware for Mac Studio
- `vendorfw/firmware.tar`: Vendor-specific firmware

### NixOS Firmware Configuration
```nix
hardware.asahi = {
  enable = true;
  peripheralFirmwareDirectory = "/boot/efi/asahi";
  extractPeripheralFirmware = true;  # Extracts at boot via asahi-fwextract
};
```

---

## M1 Ultra Specific Requirements

The Mac Studio M1 Ultra has specific hardware requirements that must be handled by the kernel:

### The 80GB Dual-Die Offset
M1 Ultra (t6002) is dual-die. Die 1 starts at `0x2000000000` physical offset.
- **Kernel Config Required**:
  - `CONFIG_ARM64_PA_BITS_48=y`
  - `CONFIG_ARM64_VA_BITS_48=y`
  - `CONFIG_NUMA=y`
  - `CONFIG_NODES_SHIFT=9`

### 16K Page Alignment
Apple Silicon enforces 16K page alignment.
- Handled automatically by `linux-asahi` kernel

### Compression
Fedora's GRUB cannot decompress ZSTD kernels.
- Must use GZIP: `CONFIG_KERNEL_GZIP=y`
- (nixos-apple-silibrium handles this automatically)

---

## Fresh Install Checklist

When performing the fresh NixOS install, verify:

- [ ] macOS is clean (recovered via Recovery or Configurator)
- [ ] `curl https://alx.sh | sh` completed successfully
- [ ] Permissive security mode enabled
- [ ] New EFI partition visible and mounted
- [ ] Firmware files extracted (`all_firmware.tar.gz`, `kernelcache.*`)
- [ ] Fresh partition created for NixOS root
- [ ] Installer boots successfully (no black screen)
- [ ] NixOS installs and boots
