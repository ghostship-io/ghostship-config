# PowerShell non-interactive patterns

Use these for Windows-side commands that must return cleanly from WSL.

## Use the explicit Windows PowerShell path

```fish
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '$env:UserName'
```

This works on the current WSL host and returns Windows PowerShell `5.1`.

## Run a one-off command

```fish
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "<command>"
```

## Running scripts from WSL

Use a Windows path with `-File`. A WSL `/mnt/c/...` path does not work with
`powershell.exe -File` on this host.

```fish
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Scripts\script.ps1'
```

## Working directory behavior

When you launch `powershell.exe` from a WSL directory, PowerShell sees the
current location as a UNC path under `\\wsl.localhost\...`.

If the command needs a normal Windows drive path, set it explicitly first:

```fish
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\\'; <command>"
```
