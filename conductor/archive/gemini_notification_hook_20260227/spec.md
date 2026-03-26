# Specification: Gemini CLI Notification Hook

## Overview
Add a global Gemini CLI hook (`AfterAgent`) that triggers a system notification using `notify-send` whenever an agent turn completes and the CLI is waiting for user input. This will provide visual and auditory feedback to the user, especially useful in WSL/Windows environments.

## Functional Requirements
- **Hook Configuration**: Configure the `AfterAgent` hook in the Gemini CLI settings (`~/.gemini/settings.json`) using Home Manager.
- **Notification Trigger**: The hook must execute `notify-send` with the following parameters:
    - **Title**: `Gemini`
    - **Message**: `Waiting for input...`
    - **Urgency**: `critical` (to ensure it triggers sound and high priority in Windows Action Center/WSL).
- **Platform Compatibility**:
    - **WSL Systems**: Utilize the existing `notify-send` bridge in `modules/common/wsl.nix`.
    - **Hardware Systems**: Ensure `libnotify` (providing `notify-send`) is available as a dependency.
- **Urgency Support**: Update the `notify-send` bridge in `modules/common/wsl.nix` to handle the urgency flag (if not already supported) to ensure "Toast" priority and sound.

## Non-Functional Requirements
- **Minimal Overhead**: The hook execution should be fast and not delay the CLI.
- **Declarative Management**: All configurations must be managed via Nix/Home Manager.

## Acceptance Criteria
- [ ] Running a Gemini agent results in a system notification after it finishes its turn.
- [ ] The notification displays the title "Gemini" and message "Waiting for input...".
- [ ] On WSL, the notification appears in the Windows Action Center with sound and high priority.
- [ ] The system builds successfully on both WSL and hardware hosts.
