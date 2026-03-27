# Troubleshooting Log: Mac Studio NixOS Migration (chill-penguin)

## Environment & Build Info
- **Target Host**: `chill-penguin2` (Mac Studio M1 Ultra)
- **Current OS**: NixOS 25.11 (Running Attempt 36 -> Transitioning to Attempt 44)
- **Migration Status**: Phase 6 (Integrating Rust and GPU Acceleration)
- **Native Build**: 
    - Latest Successful: Attempt 44 (6.14.2-asahi, Rust 1.84.0 Enabled)
- **Current State**: Kernel successfully compiled Rust core objects and asahi DRM driver with Rust 1.84.0. Final linking in progress. Next step is hardware verification and GRUB chainloading.

---

## Apple Silicon Kernel Architecture & Boot Chain

Understanding how Apple Silicon boots Linux is critical to surviving the NixOS installation process, especially when migrating from another distro like Fedora Asahi Remix.

### 1. The Boot Chain
1. **Apple Silicon Firmware (iBoot)**: The low-level hardware bootloader.
2. **m1n1 (Stage 1)**: Asahi's custom bootloader that handles hardware initialization specific to Apple Silicon and translates the Apple hardware state into a standard Linux/device-tree state.
3. **m1n1 (Stage 2 Payload)**: This is a single, concatenated binary (`boot.bin` usually found in the ESP) containing:
   - The `m1n1` stage 2 logic.
   - **Compiled Device Trees (`*.dtb`)**.
   - U-Boot.
4. **U-Boot**: Provides standard UEFI services to the next stage.
5. **GRUB / systemd-boot**: Standard Linux bootloaders. In our case, Fedora's GRUB (`/boot/grub/grub.cfg`) chainloads the NixOS kernel.
6. **Linux Kernel (`vmlinuz.efi`)**: The final payload.

### 2. The "6.18 Gap" & m1n1 DTB Concatenation
**Finding**: The `nixos-apple-silicon` repository defaults to kernel `6.18.x`. Our attempts to boot this kernel resulted in immediate Black Screens or Synchronous Aborts. 
**The Root Cause**:
- **Hardware Matching, Not OS Matching**: When `m1n1` runs, it scans the appended DTBs in its payload and picks the one that matches the hardware (e.g., Mac Studio M1 Ultra). It does *not* know which OS or kernel you are about to boot. If the payload contains 6.14 DTBs, it passes a 6.14 DTB to whatever kernel is next.
- **The Chainloading Trap**: Because we chainloaded NixOS from Fedora's existing GRUB (to keep a safe fallback), we booted the NixOS kernel using Fedora's `/boot/efi/m1n1/boot.bin`, which contained the DTBs for kernel **6.14.2**.
- **The 6.18 Incompatibility**: Kernel 6.18 introduced breaking changes to Apple Silicon device trees (specifically DART and USB-C). When the 6.18 kernel booted using the 6.14 DTB from the Fedora m1n1 payload, it encountered a hardware-level memory map violation and triggered a Synchronous Abort.
**Solution**: Stick to the 6.14.2 kernel source that perfectly matches the existing Fedora m1n1 firmware payload.

### 3. M1 Ultra Multi-Die Addressing (The 80GB Offset)
**Finding**: The M1 Ultra (t6002) is a dual-die SoC. Peripherals on the second die (Die 1) are addressed with a **`0x2000000000` (80 GB)** physical offset relative to Die 0.
**Impact**: The HDMI port on the Mac Studio is hard-wired to the Display Controller (DCP) on **Die 1**. The kernel must be compiled with `ARM64_PA_BITS_48=y`, `ARM64_VA_BITS_48=y`, `NUMA=y`, and `NODES_SHIFT="9"` to properly address this massive memory offset, otherwise it results in a Black Screen on boot.

### 4. 16K Page Alignment Constraints
**Finding**: Apple Silicon strictly enforces 16K page alignment. Standard NixOS kernels use 512-byte alignment.
**Impact**: If a kernel is built with 4K alignment, m1n1's MMU setup fails, triggering an Instruction Abort. We must use the `vmlinuz.efi` Makefile target (`makeFlags = [ "vmlinuz.efi" ]`) to get a PE32+ binary with `0x1000` FileAlignment.

---

## The NixOS Kernel Build Process (Attempt 44)

Building a custom Asahi kernel in NixOS requires bypassing standard module abstractions and calling `buildLinux` directly.

1. **Overlay Architecture & `makeOverridable`**: We define `linux-asahi` in a flake overlay. Critically, the `nixos-apple-silicon` module expects `pkgs.linux-asahi` to be a function/derivation that accepts a `_kernelPatches` argument (so it can inject its own patches). If we just assign a derivation to `linux-asahi`, the module's `.override` call will crash. We must wrap our custom kernel definition in `lib.makeOverridable ({ _kernelPatches ? [] }: ...)`.
2. **`buildLinux` Override**: We call `prev.buildLinux.override { rustc-unwrapped = ...; rustPlatform = ...; }` to inject the correct Rust toolchain, and pass custom arguments:
   - `src`: Pinned exactly to `AsahiLinux/linux` at `asahi-6.14.2-1`.
   - `structuredExtraConfig`: This is where we inject critical flags (like `KERNEL_GZIP=yes`, `RUST=yes`, and the M1 Ultra alignment flags) bypassing `defconfig` defaults.
   - `makeFlags`: Overridden to target `vmlinuz.efi`.
   - `postInstall`: A custom script to find `vmlinuz.efi` deep in the build tree and copy it to `$out/Image`, ensuring NixOS installation scripts find the correctly aligned binary.
3. **Rust Toolchain Injection**: To compile the `asahi.ko` GPU driver, the kernel needs Rust. We use `oxalica/rust-overlay` to generate a specific Rust toolchain (1.78.0) and inject it into `buildLinux` via a custom `rustPlatform` and `rustc-unwrapped` argument.

---

## Stabilization Fixes & Lessons Learned

### 1. Rust Version Gating (2024 Edition) & `rustPlatform` Mismatch
**Problem**: Rust 1.78.0 through 1.83.0 failed to build the 6.14.2 kernel source with errors related to the new Rust standard library features. Specifically, 6.14.2 uses `impl Trait + use<'_>`, which is a Rust 2024 feature gate.
**Cause**: 
- **Minimum Requirement**: Kernel 6.14.2 requires exactly **Rust 1.84.0+**.
- **The nixpkgs trap**: In Nixpkgs, `buildLinux` relies on `rustPlatform.rustLibSrc` to map the Rust standard library (`core`, `alloc`). If you override `rustc` but don't explicitly pass a custom `rustPlatform` built with that exact same `rustc`, the compiler will use the system's default `rust-src` (e.g., 1.91.1), causing massive syntax errors inside the standard library itself.
- **Compiler Persistence**: Even when overriding `rustc-unwrapped`, `callPackage` magic often re-injects the system-wide 1.91.1 compiler into `nativeBuildInputs`.
**Solution**: 
1. Use **Rust 1.84.0** (pinned via `rust-overlay`).
2. Perform **"Builder Surgery"** in the overlay: manually filter `nativeBuildInputs` to remove any derivation containing "rustc" and inject the pinned 1.84.0 toolchain.
3. Explicitly set `RUST_LIB_SRC` in the derivation environment to the toolchain's internal library path.

### 2. Compression Formats (GZIP vs ZSTD)
**Problem**: The kernel build silently defaulted to ZSTD compression, causing the Fedora GRUB bootloader to crash when trying to parse the `zimg` header.
**Cause**: Nixpkgs `common-config.nix` overrides `KERNEL_ZSTD=y`. If we rely on `defconfig`, ZSTD wins.
**Solution**: Explicitly set `KERNEL_GZIP = lib.mkForce yes;` and `KERNEL_ZSTD = lib.mkForce no;` in the `structuredExtraConfig` block.

### 3. Builtin Drivers vs Modules (The "Emergency Shell" Fix)
**Problem**: The system would drop to an emergency shell unable to mount the Btrfs root filesystem.
**Cause**: The NixOS initrd didn't have the necessary modules loaded in time for the Btrfs mount.
**Solution**: Force critical bootstrap drivers to be compiled directly into the kernel (`=y`) rather than as modules (`=m`). (e.g., `CONFIG_BTRFS_FS=y`, `CONFIG_NVME_APPLE=y`, `CONFIG_APPLE_RTKIT=y`).

### 4. The GRUB/Bootloader Nightmare
**Problem**: Automated scripts (`grub2-mkconfig`) corrupted Fedora's Boot Loader Specification (BLS) integration.
**Solution**: Abandon automated GRUB updates. We now do a surgical Python regex replacement of a custom block in `/boot/grub/grub.cfg` to safely chainload NixOS.

---

## Emergency Recovery via 1TR (When boot.bin fails)
If a bad kernel or `m1n1` payload is flashed and the system panics before reaching the network, USB boot is impossible because U-Boot never loads.
1. **Enter macOS Recovery (1TR)**: Shut down the Mac Studio. Press and **hold** the physical power button until the screen says "Loading startup options...". Select the Options gear icon.
2. **Open Terminal**: Utilities -> Terminal.
3. **Mount the EFI Partition**: `diskutil list` -> `diskutil mount disk0s5` (or whatever the EFI partition is).
4. **Restore the Backup**: `cd /Volumes/EFI/m1n1/` -> `rm boot.bin` -> `cp boot.bin.fedora.bak boot.bin`.
5. **Reboot**: Type `reboot`.

---

## Attempt Log (Recent Path to Stability)

### Attempt 29: First Boot Success
- **Action**: Made Btrfs/CRC32C and Apple drivers builtin. Stripped Rust. Fixed alignment.
- **Result**: Booted successfully to a headless shell.

### Attempts 30-36: The Rust Struggle
- **Action**: Attempted to re-enable Rust to get full GPU acceleration.
- **Result**: Repeated failures due to Nix cross-compilation errors and Rust toolchain version mismatches. Attempt 36 abandoned Rust for a stable headless baseline.

### Attempt 44: The Rust Breakthrough
- **Action**: Re-baselined to Attempt 29. Discovered the `rustPlatform.rustLibSrc` mapping bug in Nixpkgs. Pinned Rust to 1.81.0, injected the custom `rustPlatform`, and enforced GZIP compression.
- **Result**: Compilation succeeded. Rust integration successful. Awaiting hardware verification.
