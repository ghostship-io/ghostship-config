# Specification: Port Legacy WSL Features

## Overview
This track aims to port remaining features and configurations from the legacy `old/wsl-config` (Ansible) repository to the new NixOS flake-based configuration. This includes system-level utilities, user packages, SSH configurations, and a full Fish shell setup.

## Functional Requirements
- **WSL SMB Mounting (mount-z):**
    - Implement a systemd service (or equivalent) to mount a Windows SMB share to `/mnt/z`.
    - Use `sops-nix` to securely manage `SMB_USER` and `SMB_PASS`.
    - Ensure the mount only occurs if the drive is accessible.
- **Standard Package Audit:**
    - Audit and ensure the following packages are present in the common NixOS modules: `7zip`, `bat`, `cifs-utils`, `direnv`, `fastfetch`, `fd`, `eza`, `ripgrep-all`, `starship`, `zoxide`.
- **SSH Configuration:**
    - Enable `ssh-agent` as a user-level systemd service.
    - Declaratively manage `~/.ssh/config` with the optimized settings from the old configuration (ControlMaster, Compression, etc.).
- **Fish Shell Implementation:**
    - Set Fish as the default shell for the `nixos` user.
    - Port aliases and configurations from `old/wsl-config/ansible/roles/fish/files/conf.d/`.
    - Configure `starship` prompt.
    - Install and manage Fish plugins (e.g., `autopair`, `sponge`, `puffer-fish`, `fish-colored-man`) using a Nix-native approach where possible. (Skipping `gitignore` and `autovenv`).

## Non-Functional Requirements
- **Reproducibility:** All configurations must be declarative and part of the NixOS flake.
- **Security:** Secrets (SMB credentials) must be managed via `sops-nix`.

## Acceptance Criteria
- [ ] `/mnt/z` is successfully mounted in WSL when the SMB share is available.
- [ ] All audited packages are available in the shell.
- [ ] `ssh-agent` is running and `~/.ssh/config` is correctly populated.
- [ ] Fish shell is the default, with the Starship prompt and all expected aliases/plugins working.

## Out of Scope
- Antigravity bridge functionality.
- Porting GUI-specific configurations not relevant to the current headless/WSL setup.
