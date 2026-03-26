# Specification: Implement Fish Shell for nixos User

## Overview
Implement the `fish` shell as the default shell for the `nixos` user, porting aliases, packages, and functions from the legacy `wsl-config` repository. The `gemini` command management will be separated into its own logical unit.

## Functional Requirements
1.  **Fish Shell Integration**:
    - Enable `fish` shell for the `nixos` user.
    - Set `fish` as the default shell for the `nixos` user.
    - Integrate `starship` prompt.
2.  **Package Porting**:
    - Install the following packages for the `nixos` user (via Home Manager):
        - `7zip`, `bat`, `cifs-utils`, `fastfetch`, `fd`, `git-lfs`, `ldns`, `lsd`, `python3Packages.pipx`, `ripgrep-all`, `zoxide`, `nodejs`.
3.  **Alias & Function Porting**:
    - Implement aliases: `c`, `cat`, `dig`, `fd`, `l`, `ld`, `lda`, `lf`, `lfa`, `ll`, `ls`, `lsd`, `rg`, `tree`, `reload`, `vissh`.
    - Implement `rmssh` function.
4.  **Plugin Management**:
    - Install fish plugins: `gitignore`, `autopair`, `sponge`, `puffer-fish`, `autovenv`, `colored-man`.
5.  **Gemini CLI Separation**:
    - Create a separate mechanism for managing the `gemini-cli` instead of a shell function that installs via `npm`. (e.g., a Nix derivation or a separate script module).

## Acceptance Criteria
- [ ] `fish` is the default shell for user `nixos`.
- [ ] All ported packages are available in the environment.
- [ ] All aliases and functions work as expected.
- [ ] `starship` prompt is active in `fish`.
- [ ] `gemini` command is available and managed separately.

## Out of Scope
- Porting configuration for other shells (bash, zsh).
- Porting Antigravity bridge setup or `agy` function.
