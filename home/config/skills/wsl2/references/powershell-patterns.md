# PowerShell Non-Interactive Patterns

## Get Windows Username
```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\$env:UserName"
```

## Check if Drive Exists
```bash
/mnt/c/Windows/System32/cmd.exe /c "IF EXIST Z:\ (EXIT 0) ELSE (EXIT 1)"
```

## Running Scripts from WSL
```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass -File "/mnt/c/Scripts/script.ps1"
```
