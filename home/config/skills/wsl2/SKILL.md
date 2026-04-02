---
name: wsl2
description: Use for Windows and WSL boundary work, including PowerShell, Windows executables, mounts, path translation, and repo-specific WSL host behavior.
---

# wsl2

Use this skill when the task crosses Linux and Windows boundaries on the WSL
develop hosts.

## Core workflow

- Prefer explicit Windows executable paths or known `.exe` commands for
  non-interactive Windows-side work.
- Use `~/win-home` or `/mnt/c/...` for Windows files, and treat `/mnt/z` as a
  lazy mount that may need checking before use.
- For system changes inside WSL, use a root shell. For Windows admin tasks,
  tell the user to run the command in an elevated Windows terminal.

## Read when needed

- [PowerShell patterns](references/powershell-patterns.md)
- [Interop tools](references/interop-tools.md)
- [Troubleshooting](references/wsl-troubleshooting.md)
