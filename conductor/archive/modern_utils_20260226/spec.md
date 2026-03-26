# Specification: Modern Terminal Utilities Integration

## Overview
Enhance the terminal environment by integrating modern, user-friendly utilities (`duf`, `du-dust`, `procs`, `gping`, `fzf`, `glow`) into the NixOS and Home Manager configurations.

## Functional Requirements
- **System-Wide Utilities**:
    - Add `fzf` to `modules/common/default.nix`.
    - Enable Fish shell integration for `fzf` (keybindings, etc.).
- **User-Specific Utilities**:
    - Add `duf`, `du-dust`, `procs`, `gping`, `duff`, and `glow` to `home/nixos.nix`.
- **Aliases**:
    - Configure Fish aliases in `home/nixos.nix`:
        - `df` -> `duf`
        - `du` -> `dust`
        - `ps` -> `procs`
        - `ping` -> `gping`

## Acceptance Criteria
- [ ] `fzf` is available system-wide with Fish integration active.
- [ ] `duf`, `dust`, `procs`, `gping`, `duff`, and `glow` are available for the `nixos` user.
- [ ] Running `df`, `du`, `ps`, or `ping` executes the corresponding modern utility.
- [ ] `nixos-rebuild switch` applies the configuration successfully.
