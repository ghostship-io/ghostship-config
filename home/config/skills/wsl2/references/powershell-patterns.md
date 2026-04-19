# PowerShell non-interactive patterns

Use these for Windows-side commands that must return cleanly from WSL.

WSL hosts in this repo do not import bare `powershell.exe` into the Linux PATH. Use the repo-managed wrapper when possible, or call the explicit Windows path directly.

## Use the repo-managed wrapper

```fish
win-powershell -Command '$env:UserName'
```

The wrapper delegates to the real Windows PowerShell path with `-NoProfile -ExecutionPolicy Bypass`.

## Use the explicit Windows PowerShell path directly

```fish
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$env:UserName'
```

## Run a one-off command

```fish
win-powershell -Command "<command>"
```

## Running scripts from WSL

Use a Windows path with `-File`. A WSL `/mnt/c/...` path does not work with `-File` on this host.

```fish
win-powershell -File 'C:\Scripts\script.ps1'
```

## Working directory behavior

When you launch Windows PowerShell from a WSL directory, PowerShell sees the current location as a UNC path under `\\wsl.localhost\...`.

If the command needs a normal Windows drive path, set it explicitly first:

```fish
win-powershell -Command "Set-Location 'C:\\'; <command>"
```
