# WSL2 Boundary Troubleshooting

## 1. Network Issues
- Check `/etc/resolv.conf`. If it doesn't match the Windows host DNS, `services.resolved` might be interfering.
- Try `ipconfig.exe` to see if the virtual ethernet adapter is active.

## 2. Permission Denied on /mnt/c/
- Ensure the Windows file is not locked by another process.
- Check if `wsl.conf` automount options are set correctly.

## 3. Command Not Found
- Verify the `.exe` extension is included.
- Check if Windows Interop is enabled in `wsl.conf`.
