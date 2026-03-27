# Research: Compiling NixOS Kernels as EFI Images (AArch64)

## Background
On Apple Silicon (Mac M1/M2/Ultra), the boot process typically involves `m1n1 -> U-Boot -> GRUB`. Fedora Asahi Remix provides a kernel formatted as a `PE32+ executable for EFI (application)`. NixOS, by default on AArch64, produces a raw `Image` binary. 

While modern UEFI firmware can often boot a raw `Image` if it contains an EFI stub, the Fedora environment/GRUB setup on `chill-penguin` appears to strictly require the PE32+ EFI application format.

## Key Findings

### 1. Kernel Formats on AArch64
- **`Image`**: The standard uncompressed kernel binary.
- **`Image.gz`**: Compressed kernel binary.
- **`vmlinuz.efi`**: A compressed kernel binary wrapped in a PE/COFF (PE32+) header, making it a valid EFI application.

### 2. Required Kernel Configuration
To produce a PE32+ EFI application, the following must be enabled:
- `CONFIG_EFI_STUB=y`: Embeds the EFI loader stub.
- `CONFIG_EFI=y`: General EFI support.
- `CONFIG_EFI_ZBOOT=y`: Enables the "Generic EFI zboot" infrastructure, which creates the `vmlinuz.efi` target.

### 3. Nixpkgs Build Mechanism
- **`kernelTarget`**: This parameter in `pkgs.buildLinux` (or `pkgs.linuxManualConfig`) tells the kernel's `Makefile` which target to build. On AArch64, it defaults to `"Image"`.
- **Targeting EFI**: To get the Fedora-matching format, `kernelTarget` must be set to `"vmlinuz.efi"`.
- **NixOS Options**: There is no standard `boot.kernelTarget` option in the NixOS module system; it must be overridden at the package/derivation level (usually via an overlay).

### 4. Implementation Strategy for Asahi/NixOS
To ensure compatibility with the Asahi bootloader while keeping NixOS happy:
1. Use `pkgs.buildLinux` with `kernelTarget = "vmlinuz.efi"`.
2. Enable `EFI_ZBOOT = yes` in the structured configuration.
3. In the `postInstall` phase, copy `vmlinuz.efi` to `$out/Image`. This ensures that NixOS's default installation scripts (which look for `Image` on AArch64) find the new EFI-wrapped binary.

## Comparison Table

| Feature | Fedora Asahi Kernel | Default NixOS AArch64 | Our Aligned NixOS Kernel |
| :--- | :--- | :--- | :--- |
| **File Format** | PE32+ EFI Application | ARM64 Boot Executable | PE32+ EFI Application |
| **Compression** | Compressed (ZBOOT) | Uncompressed | Compressed (ZBOOT) |
| **EFI Stub** | Integrated | Integrated (but raw) | Integrated (PE/COFF) |
| **Target Name** | `vmlinuz` | `Image` | `vmlinuz.efi` (mapped to `Image`) |

## Verification
The format can be verified using the `file` command:
```bash
# Expected output for success:
# vmlinuz-nixos: PE32+ executable for EFI (application), ARM64
```
