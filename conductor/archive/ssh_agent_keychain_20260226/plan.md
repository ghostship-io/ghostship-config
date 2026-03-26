# Implementation Plan: SSH Agent with Systemd and Fish Shell Integration

## Phase 1: SSH Agent Systemd Service and Fish Integration [checkpoint: 8e5a0c1]

- [x] Task: Remove `keychain` from `home.packages` and `keychain` initialization from `programs.fish.interactiveShellInit`. 6e41f1b
- [x] Task: Ensure `services.ssh-agent.enable = true;` is configured in `home/nixos.nix`. 324aa78
- [x] Task: Create a custom Fish script to detect and configure `ssh-agent` environment variables on shell login. 4cbb9f8
- [x] Task: Conductor - User Manual Verification 'Phase 1: SSH Agent Systemd Service and Fish Integration' (Protocol in workflow.md) 8e5a0c1

## Phase 2: SSH Client Configuration [checkpoint: 0ecf21c]

- [x] Task: Configure `programs.ssh.addKeysToAgent`. b4b053e
- [x] Task: Conductor - User Manual Verification 'Phase 2: SSH Client Configuration' (Protocol in workflow.md) 0ecf21c