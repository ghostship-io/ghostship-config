# Specification: Remove Legacy Windows Notification Bridge

## Overview
Remove the `win-notify` utility and all its integrations across the codebase and documentation. This is a cleanup task to prepare for a different notification approach.

## Functional Requirements
1.  **Code Removal**:
    -   Delete the `win-notify` shell script definition in `modules/common/wsl.nix`.
    -   Remove all integrations and calls to `win-notify` in `home/wsl.nix` (Fish hooks, etc.).
    -   Remove the high-demand notification logic using `win-notify` in `modules/common/gemini.nix`.
2.  **Documentation Update**:
    -   Remove `win-notify` from the **Tech Stack** (`conductor/tech-stack.md`).
3.  **Track Management**:
    -   Remove the "Windows Notifications for WSL2" entry from `conductor/tracks.md`.
    -   Permanently delete the track directory `conductor/tracks/win_notifications_20260227/`.

## Acceptance Criteria
-   `sudo nixos-rebuild build --flake .#launch-octopus` succeeds without errors.
-   The `win-notify` command is no longer present in the system environment.
-   A recursive search for `win-notify` in the repository returns no results (excluding the new track files).

## Out of Scope
-   Implementing any replacement notification system.
