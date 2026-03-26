# Specification: Add inshellisense and integrate it into Fish

## Overview
Integrate `inshellisense`, an IDE-style command-line autocomplete tool, into the Fish shell environment managed via Home Manager for the `nixos` user.

## Functional Requirements
- **User-Specific Installation**: Add `inshellisense` to the `home.packages` list in `home/nixos.nix`.
- **Fish Integration**: Configure Fish to automatically initialize `inshellisense` in interactive sessions. This involves adding `inshellisense --init fish | source` (or the appropriate initialization command) to the Fish configuration.
- **Declarative Management**: Ensure all configurations are managed through Nix files and Home Manager.

## Non-Functional Requirements
- **Performance**: The initialization should not noticeably slow down the Fish shell startup.
- **Maintainability**: Use standard Home Manager patterns for Fish configuration.

## Acceptance Criteria
- [ ] `inshellisense` is installed in the `nixos` user's profile.
- [ ] Opening a new Fish shell session automatically activates `inshellisense` autocomplete features.
- [ ] Running `nixos-rebuild switch` applies the configuration successfully.

## Out of Scope
- System-wide installation for other users.
- Customizing `inshellisense` keybindings or themes (unless required for basic functionality).
