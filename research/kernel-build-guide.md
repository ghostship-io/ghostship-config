# Asahi Linux on NixOS: Kernel & Build Architecture Guide

This guide documents the complete end-to-end process of how the Asahi Linux kernel is built, configured, and integrated into NixOS, specifically tailored for the Mac Studio M1 Ultra.

## 1. The Apple Silicon Boot Chain

Unlike standard x86 PCs, Apple Silicon does not boot directly from an EFI partition into GRUB.

1. **iBoot (Firmware)**: Apple's immutable low-level bootloader.
2. **m1n1 (Stage 1)**: Asahi Linux's custom bootloader. It translates Apple's proprietary hardware state into a standard Linux device-tree environment.
3. **m1n1 (Stage 2 Payload)**: During OS installation, the `asahi-installer` concatenates `m1n1.bin`, hardware-specific **Device Trees (`*.dtb`)**, and `U-Boot` into a single, massive file usually located at `/boot/efi/m1n1/boot.bin`.
    * **CRITICAL**: The DTBs are hardcoded into this payload. They *must* match the expectations of the Linux kernel you are trying to boot. If the payload has 6.14 DTBs, but you boot a 6.18 kernel, the kernel will panic or trigger a hardware Synchronous Abort due to memory map mismatches (the "6.18 Gap").
4. **U-Boot**: Provides the standard UEFI environment.
5. **GRUB / systemd-boot**: The standard Linux bootloader, which loads the kernel.
6. **Linux Kernel (`vmlinuz.efi`)**: The final executed kernel.

---

## 2. Kernel Hardware Requirements (M1 Ultra)

The Mac Studio M1 Ultra has several strict hardware requirements that standard NixOS kernels do not fulfill:

### The 80GB Dual-Die Offset
The M1 Ultra is essentially two M1 Max dies bridged together. The second die (Die 1) has a massive physical memory offset of `0x2000000000` (80 GB). Crucially, the HDMI Display Controller (DCP) is physically located on Die 1. 
* **Kernel Fix**: The kernel must be compiled with `ARM64_PA_BITS_48=y`, `ARM64_VA_BITS_48=y`, `NUMA=y`, and `NODES_SHIFT="9"`. Without these, the kernel cannot address the second die, resulting in an immediate black screen when the framebuffer initializes.

### 16K Page Alignment
Apple Silicon strictly enforces 16K memory page alignment.
* **Kernel Fix**: The kernel payload must be built with `make vmlinuz.efi` to generate a PE32+ `zimg` that respects a `0x1000` FileAlignment constraint.

### Compression
Depending on the bootloader (specifically Fedora's GRUB), certain compression algorithms (like `zstd`) may crash the GRUB payload parser.
* **Kernel Fix**: Explicitly force `KERNEL_GZIP=y` and disable `zstd` in the kernel config.

---

## 3. The NixOS Build Process (The `flake.nix` Overlay)

To compile the kernel with all these specific constraints, we use a global `nixpkgs` overlay in our `flake.nix`.

### A. Overriding `linux-asahi`
The `nixos-apple-silicon` module expects a package named `linux-asahi` that accepts a `_kernelPatches` argument via `.override`. To satisfy this while completely replacing the kernel, we use `lib.makeOverridable`:

```nix
linux-asahi = final.lib.makeOverridable ({ _kernelPatches ? [] }:
  # Custom kernel build logic here
) { };
```

### B. Injecting the Rust Toolchain
Kernel 6.14.2 requires **Rust 1.84.0+** because it utilizes newer language features (`impl Trait + use<'_>`) in the standard library mapping. If an older version (like 1.78.0) is used, compilation fails. Conversely, if the system default (e.g., 1.91.1) is used, it often conflicts with the 6.14.2 source expectations.

We resolve this by performing **"Ultimate Surgery"** on the kernel derivation:
1.  **Input Filtering**: We manually filter `nativeBuildInputs` to remove any derivation containing "rustc" (to prevent `callPackage` from re-injecting 1.91.1).
2.  **Pinned Injection**: We inject a precisely pinned `rust-bin.stable."1.84.0".minimal` with `rust-src` extension.
3.  **Environment Sync**: We explicitly set `RUST_LIB_SRC` in the `env` attribute to point to the toolchain's library path, ensuring the compiler finds the correct matching standard library sources.

```nix
linux-asahi-custom = let
  rust-toolchain = final.rust-bin.stable."1.84.0".minimal.override { extensions = [ "rust-src" ]; };
  base-kernel = final.buildLinux { ... rustSupport = true; ... };
in base-kernel.overrideAttrs (old: {
  nativeBuildInputs = (lib.filter (x: !(lib.hasInfix "rustc" (x.name or ""))) old.nativeBuildInputs) ++ [ rust-toolchain ];
  env = (old.env or {}) // { RUST_LIB_SRC = "${rust-toolchain}/lib/rustlib/src/rust/library"; };
});
```

### C. Executing the Build (`customBuildLinux`)
We pass our strict requirements to the kernel builder:
1. **Source**: Pinned to the exact `AsahiLinux/linux` commit (`asahi-6.14.2-1`).
2. **`structuredExtraConfig`**: We force all of our critical flags (`KERNEL_GZIP`, `RUST`, `ARM64_PA_BITS_48`, etc.) here, guaranteeing they take precedence over `asahi_defconfig`.
3. **`makeFlags`**: We add `"vmlinuz.efi"` to force the correct alignment.
4. **`postInstall`**: A custom shell script runs at the end of the compilation to dig the `vmlinuz.efi` file out of the build tree and copy it to `$out/Image`.

---

## 4. Full Remote Build Execution

Because the Mac Studio has 20 cores, building the kernel locally on a weaker machine (or an x86 host) is inefficient. We execute the build remotely.

1. **Sync Configuration**: 
   `rsync -avz --exclude .git . chill-penguin2:/home/nixos/nixos-config/`
2. **Trigger Remote Build (Background)**:
   ```bash
   ssh chill-penguin2 "cd /home/nixos/nixos-config && nohup nix build .#nixosConfigurations.chill-penguin.config.system.build.toplevel --print-build-logs --impure > build.log 2>&1 &"
   ```
3. **Monitor**:
   ```bash
   ssh chill-penguin2 "tail -f /home/nixos/nixos-config/build.log"
   ```
4. **Deployment**:
   Once the closure is built in `/nix/store`, the new kernel `Image` (which is actually the aligned `vmlinuz.efi`) is copied into `/boot`, and the system GRUB configuration is updated via a surgical Python script to chainload the new generation.
