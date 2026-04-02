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
- Prefer `/mnt/c/...` for Windows files, and treat `/mnt/z` as a lazy mount
  that may need checking before use.
- Use `wslpath` for path conversion:
  `wslpath -u 'C:\path\to\file'` for Windows to Linux,
  `wslpath -w /linux/path` for Linux to Windows-style,
  and `wslpath -m /linux/path` for slash-separated Windows-style paths.
- For system changes inside WSL, use a root shell. For Windows admin tasks,
  tell the user to run the command in an elevated Windows terminal.

## Read when needed

- [PowerShell patterns](references/powershell-patterns.md)
- [Interop tools](references/interop-tools.md)
- [Troubleshooting](references/wsl-troubleshooting.md)
