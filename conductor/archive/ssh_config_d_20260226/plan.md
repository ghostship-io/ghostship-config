# Implementation Plan: SSH Config.d Directory Management

## Phase 1: SSH Config.d Management

- [x] Task: Configure Home Manager `home.file` to create and manage `~/.ssh/conf.d/` with correct permissions. a345e0c
- [x] Task: Configure `programs.ssh` to include `~/.ssh/conf.d/*`. 8eb0a2a
- [x] Task: Conductor - User Manual Verification 'Phase 1: SSH Config.d Management' (Protocol in workflow.md) 8eb0a2a

## Phase 2: SSH Configuration Refactor and Agent Timeout [checkpoint: 9d6948b]

- [x] Task: Consolidate all SSH options into a single `matchBlocks."*"` block. 9c178fd
- [x] Task: Disable default Home Manager SSH configuration (`enableDefaultConfig = false`). 86e9bfa
- [x] Task: Configure `services.ssh-agent` with a 15-minute key timeout (`-t 15m`). 41c636e
- [x] Task: Align `matchBlocks` with MyNixos structured options. 2b600b6
- [x] Task: Conductor - User Manual Verification 'Phase 2: SSH Configuration Refactor and Agent Timeout' (Protocol in workflow.md) 9d6948b