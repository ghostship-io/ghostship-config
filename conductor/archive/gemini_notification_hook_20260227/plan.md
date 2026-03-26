# Implementation Plan: Gemini CLI Notification Hook

## Phase 1: Infrastructure and Bridge Update [checkpoint: 112fb6e]
- [x] Task: Update the `notify-send` bridge in `modules/common/wsl.nix` to handle the `-u` (urgency) flag. 19a8502
    - [x] Ensure `-u critical` is parsed.
    - [x] Update the PowerShell snippet to ensure a "Toast" with sound and priority is generated for critical urgency.
- [x] Task: Add `pkgs.libnotify` to `environment.systemPackages` in `modules/common/default.nix` for non-WSL system support. 095f929
- [x] Task: Conductor - User Manual Verification 'Phase 1: Infrastructure' (Protocol in workflow.md) 112fb6e

## Phase 2: Configuration and Hook Integration [checkpoint: 5138cf8]
- [x] Task: Configure the `AfterAgent` hook in `home/nixos.nix` via Home Manager. 7d21434
    - [x] Merge the existing `settings.json` content (general, security, and context settings) with the new `hooks` section.
    - [x] Create `home.file.".gemini/settings.json"` with the merged JSON content.
    - [x] Implement the `AfterAgent` hook to call `notify-send "Gemini" "Waiting for input..." -u critical`.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Configuration' (Protocol in workflow.md) 5138cf8

## Phase 3: Final Verification [checkpoint: d0c3181]
- [x] Task: Apply configuration with `sudo nixos-rebuild switch --flake .#launch-octopus`. manual
- [x] Task: Verify the notification appears when a Gemini agent finishes its turn. manual
- [x] Task: Verify that the notification has sound and high priority in Windows (on WSL). manual
- [x] Task: Verify `notify-send` works correctly on hardware systems (Mac Studio) if possible. manual
- [x] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md) d0c3181
