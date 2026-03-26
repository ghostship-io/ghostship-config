# Specification: SSH Agent with Systemd and Fish Shell Integration

## Overview
Implement a user-specific SSH agent by launching it as a `systemd` user service via Home Manager's `services.ssh-agent`. Integration with the Fish shell will be handled by a custom script that detects the running agent's environment variables and sets them in each shell session, avoiding the use of `keychain`.

## Functional Requirements
- **Home Manager `services.ssh-agent`**: Configure `services.ssh-agent.enable = true;` in `home/nixos.nix` to launch `ssh-agent` as a persistent user service.
- **Fish Shell Integration Script**:
    - Remove `keychain` from `home.packages` and any `keychain` initialization from `programs.fish.interactiveShellInit`.
    - Create a custom Fish shell script, integrated into `programs.fish.interactiveShellInit`, that will:
        - Detect if an `ssh-agent` process (launched by `systemd`) is already running.
        - If an agent is found, extract its `SSH_AUTH_SOCK` and `SSH_AGENT_PID` environment variables.
        - Set these variables in the current Fish shell session.
        - If no agent is found (e.g., `systemd` service hasn't started yet), do nothing or provide a fallback.
- **SSH Client Configuration**: Configure `programs.ssh.addKeysToAgent = "yes"`. This ensures keys are added to the agent on first use.

## Non-Functional Requirements
- **Persistence**: The `ssh-agent` must persist across user logouts and reboots, managed by `systemd`.
- **Seamless Login**: The Fish shell script should integrate with the existing `ssh-agent` on shell login without user intervention or noticeable delay.
- **No Duplicate Agents**: The setup must ensure only one `ssh-agent` instance runs per user.
- **Simplicity**: Avoid `keychain` utility.

## Acceptance Criteria
- [ ] `keychain` is not installed or referenced.
- [ ] `services.ssh-agent.enable = true;` is configured in `home/nixos.nix`.
- [ ] A user-level `ssh-agent` is running as a `systemd` service.
- [ ] Opening a new Fish shell correctly sets `SSH_AUTH_SOCK` and `SSH_AGENT_PID` from the `systemd`-launched agent.
- [ ] Only one `ssh-agent` process is running after opening multiple Fish shells.
- [ ] Running `ssh` with a key for the first time automatically adds that key to the agent (verify with `ssh-add -l`).

## Out of Scope
- `keychain` utility.
- GPG-agent or `gpg-connect-agent` configuration.
- Custom `systemd` unit files for `ssh-agent` (relying on Home Manager's `services.ssh-agent`).