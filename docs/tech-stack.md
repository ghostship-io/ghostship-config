# Tech Stack: Unified NixOS Configuration Repository

## Core Nix Ecosystem
- **Nix & Nix Flakes**: The foundation for dependency management, reproducible builds, and standardized outputs.
- **NixOS**: The primary operating system for all managed hosts.
- **Home Manager**: For managing user-level configurations and dotfiles across all systems.

## Hardware Support (Apple Silicon)
- **Kernel**: Official Asahi 6.19.9 (provided by `nixos-apple-silicon`).
- **Firmware Handling**: `asahi-fwextract` used during system activation; uncompressed firmware store (`firmwareCompression = "none"`) to ensure kernel compatibility.
- **Cross-Compilation**: Cross-compiled ARM64 installer built on x86_64 using `.#installer-bootstrap`.
- **nixos-apple-silicon**: Community-maintained repository of optimized hardware configurations.

## Deployment & Automation
- **Git-Based Auto-Upgrades**: Use `system.autoUpgrade` to automatically pull, build, and switch to new configurations from the `main` branch.
- **nixos-rebuild**: The primary tool for local system management and initial bootstrapping.

## Security & Secrets
- **sops-nix**: Integration of Mozilla SOPS with NixOS for secure, encrypted secret management (using `age` or `gpg`).
- **Custom Secret Scripts**: `secrets-get-public-key`, `secrets-add-key`, `secrets-remove-key`, and `secrets-reencrypt` for per-host key management.

## Development & Utility Tools
- **nh (Nix Helper)**: A modern, user-friendly wrapper for common Nix CLI operations.
- **direnv & nix-direnv**: For automatic, fast, and persistent development environment loading.
- **nvd (Nix Visual Diff)**: For analyzing differences between Nix package generations.
- **comma (, )**: To run any binary from nixpkgs without permanent installation.
- **nix-ld**: For running dynamically linked executables intended for generic Linux environments (e.g., VS Code Remote Server).
- **Modern CLI Tools**: eza (replacement for ls), bat, fd, zoxide, jq, and starship for a feature-rich shell experience.
- **Fish Shell**: The primary interactive shell, pre-configured with aliases and plugins.

## AI & Automation
- **AGENT CLI**: Local AI agent interface with custom Nix packaging and Home Manager configuration.
- **browser-use MCP**: Model Context Protocol server for browser automation, integrated with Nix-native browser binaries and using headless mode.
- **AGENT Global Instructions**: Distilled expert system definitions and personas managed via a global `gemini.md` in Home Manager.
