# Specification: WSL Username Discovery Fix

## Overview
The current method for discovering the Windows user's home directory in WSL via `powershell.exe -Command 'Write-Host -NoNewline $env:USERPROFILE'` is causing issues or failures in some environments. This track updates the discovery logic to use the Windows username instead and construct the path to the user's home directory.

## Functional Requirements
- **Update Discovery Command**: Use `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -Command '$env:UserName' | tr -d ''` to retrieve the Windows username.
- **Construct Home Path**: Use the discovered username to identify the Windows user home (e.g., `/mnt/c/Users/<Username>`).
- **Update Symlink Logic**: Ensure the `~/win-home` symlink in the NixOS user's directory correctly points to the Linux-translated path of the Windows user's home.
- **Handle CRLF**: Ensure the output from PowerShell is properly stripped of carriage returns (``).

## Non-Functional Requirements
- **Robustness**: The script should handle cases where PowerShell might not be at the exact path or fails to return a username (though the provided path is standard for Windows).
- **Global Application**: This change should be the default for all hosts using the `wsl.nix` module.

## Acceptance Criteria
- [ ] The PowerShell command for username discovery is updated in `modules/common/wsl.nix`.
- [ ] The `~/win-home` symlink is correctly created and points to the Windows user's home directory.
- [ ] The discovery logic is tested and verified as working correctly.

## Out of Scope
- Supporting Windows installations on drives other than `C:`.
- Supporting custom Windows user profile locations outside of `C:\Users`.
