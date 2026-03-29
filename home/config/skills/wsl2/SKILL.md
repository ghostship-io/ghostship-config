---
name: wsl2
description: Expert in WSL2 (Windows Subsystem for Linux) operations, Windows interop, and cross-platform development. Use when the agent needs to run PowerShell, Windows binaries, manage WSL-specific mounts, or handle Windows/Linux filesystem boundaries.
category: system
risk: medium
source: community
date_added: "2026-02-15"
---

# WSL2 Expert Skill

This skill provides specialized knowledge for operating within a WSL2 environment, focusing on Windows interoperability, non-interactive execution of Windows tools, and managing shared filesystems.

## Core Directives

### 1. Windows Interoperability (Interop)
- **Running Binaries**: Windows binaries (`.exe`) can be executed directly from the WSL shell if they are in the Windows PATH or via absolute paths to `/mnt/c/`.
- **Non-Interactive Execution**:
    - **PowerShell**: Use `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "<cmd>"` for reliable, non-interactive execution.
    - **CMD**: Use `/mnt/c/Windows/System32/cmd.exe /c "<cmd>"` for simple Windows commands.
- **Escaping**: When passing complex strings or paths from Bash/Fish to PowerShell, ensure single quotes are escaped (`' -> ''`) and variables are appropriately quoted to avoid shell expansion.

### 2. Filesystem & Mounts
- **Windows Drives**: Automatically mounted under `/mnt/`. (e.g., C: drive is `/mnt/c/`).
- **User Profile**: The Windows user home directory is available via the `~/win-home` symlink (e.g., `/home/nixos/win-home`) or directly at `/mnt/c/Users/<WindowsUser>/`.
- **Z Mount (`/mnt/z`)**: Managed as a direct NFS mount on WSL hosts. It is mounted lazily via systemd automount, so always check whether it is currently mounted before assuming the share is available.
- **WSLENV**: Use the `WSLENV` environment variable to share and translate paths between environments (e.g., `USERPROFILE/p`).

### 3. Privileged Operations
- **Linux Privilege Escalation**: Use a root shell for NixOS system changes or privileged file operations within WSL.
- **UAC (Windows)**: WSL cannot natively escalate to "Run as Administrator" for Windows binaries. If a Windows command requires administrative privileges (e.g., modifying system-wide registry or protected files), you MUST ask the user to run the command in an elevated Windows PowerShell terminal.

### 4. WSL2 Specific Quirks
- **Systemd**: Managed via `wsl.enable = true` in the NixOS configuration.
- **Networking**: `services.resolved` is disabled; WSL manages `/etc/resolv.conf`. If network issues occur, check Windows host DNS settings.
- **Docker**: Integrated via Docker Desktop. The socket is typically shared; ensure the user is in the `docker` group.
- **Notifications**: Use the `notify-send` bridge (which forwards to Windows Toast notifications) for system alerts.

## Workflow References

- **PowerShell Examples**: See [powershell-patterns.md](references/powershell-patterns.md) for non-interactive snippets.
- **Interop Tools**: See [interop-tools.md](references/interop-tools.md) for a list of common Windows tools available.
- **Troubleshooting**: See [wsl-troubleshooting.md](references/wsl-troubleshooting.md) for common boundary issues.

## Interaction Protocol
1. **Identify Boundary**: Determine if the task is Linux-native, Windows-native, or cross-platform.
2. **Path Translation**: Always use absolute paths or the `~/win-home` symlink when referencing Windows files.
3. **Escalation**: Proactively warn the user if a Windows-side operation likely requires Administrator privileges.
