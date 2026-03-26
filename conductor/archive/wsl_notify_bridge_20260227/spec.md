# Specification: WSL notify-send Bridge

## Overview
Implement a `notify-send` compatible Bash script for the NixOS/WSL environment. This script will act as a bridge, translating Linux notification requests into Windows toast notifications using `powershell.exe`. This allows applications running in WSL to provide native visual feedback to the user on the Windows host.

## Functional Requirements
- **Standard Compatibility**: The bridge must support the basic `notify-send` syntax: `notify-send [OPTIONS] <SUMMARY> [BODY]`.
- **PowerShell Integration**: The Bash script will construct and execute a PowerShell command string targeting the Windows host's Action Center.
- **Support for Key Flags**:
  - `-a, --app-name=APP_NAME`: Specify the application name.
  - `-i, --icon=ICON`: Specify an icon (if possible, translate Linux paths or support common Windows icon paths).
  - `-u, --urgency=LEVEL`: Support `low`, `normal`, and `critical` urgency levels.
  - `-t, --expire-time=TIME`: Support notification timeout (if supported by Windows toast notifications).
- **In-line Logic**: The PowerShell logic should be contained within the Bash script as a string to avoid external file dependencies on the Windows host.
- **NixOS Integration**: The script should be packaged as a Nix package and included in the system environment, likely via `modules/common/wsl.nix`.

## Functional Constraints
- The implementation will use `powershell.exe` to execute the notification logic.
- Path translation for icons should be handled if the path resides on the Linux filesystem but needs to be accessed by Windows.

## Acceptance Criteria
- [ ] Running `notify-send "Hello" "World"` in the WSL terminal displays a Windows toast notification with the title "Hello" and body "World".
- [ ] Running `notify-send -a "My App" "Update" "Complete"` displays the notification attributed to "My App".
- [ ] The command is available system-wide in the WSL environment.
- [ ] The implementation is documented in the NixOS configuration.

## Out of Scope
- Support for complex notification actions (buttons, inputs).
- Support for interactive sound management beyond standard Windows notification sounds.
- Support for complex HTML/Markdown formatting in the notification body beyond what Windows toast notifications support.
