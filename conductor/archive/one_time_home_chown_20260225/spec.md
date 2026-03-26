# Specification: One-Time Home Directory Ownership Fix

## Overview
Ensure correct file ownership for the `nixos` user by running a one-time `chown -R nixos:nixos` command on the home directory via a Home Manager activation script.

## Functional Requirements
- **Activation Script**: Add a Home Manager activation script (`home.activation`).
- **Sentinel File**: Use a sentinel file at `/home/nixos/.local/state/nix/home_chown.done`.
- **Ownership Correction**: If the sentinel file is missing, run `chown -R nixos:nixos /home/nixos`.
- **Sentinel Creation**: Create the sentinel file and its parent directory `/home/nixos/.local/state/nix` after the chown.

## Acceptance Criteria
- [ ] `chown -R nixos:nixos` runs once if the sentinel is missing.
- [ ] Sentinel file created at `/home/nixos/.local/state/nix/home_chown.done`.
- [ ] Subsequent rebuilds do not re-run the chown.
