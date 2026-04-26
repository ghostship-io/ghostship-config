# Common Windows Interop Tools

WSL hosts in this repo import the Windows PATH into the Linux shell and use patched envfs for Linux/FHS paths. Envfs filters Windows/DrvFS PATH binaries out of `/usr/bin`, but deterministic Windows flows should still use explicit `/mnt/c/...` paths or repo-managed wrappers.

- **PowerShell**: `win-powershell -Command '$env:UserName'` - Launch Windows PowerShell through the repo-managed wrapper.
- **Explorer**: `/mnt/c/Windows/explorer.exe .` - Open current folder in Windows Explorer.
- **Wsl-Open**: `wsl-open <file>` - Open file in default Windows application.
- **CMD**: `/mnt/c/Windows/System32/cmd.exe /c ver` - Launch Windows Command Prompt.
- **Task Manager**: `/mnt/c/Windows/System32/taskmgr.exe` - Launch Windows Task Manager.
- **Systeminfo**: `/mnt/c/Windows/System32/systeminfo.exe` - View Windows system details.
- **Ipconfig**: `/mnt/c/Windows/System32/ipconfig.exe` - View Windows network configuration.
- **Clip**: `/mnt/c/Windows/System32/clip.exe` - Pipe output to Windows clipboard.
