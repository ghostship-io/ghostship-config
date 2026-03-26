# Specification: SSH Config.d Directory Management

## Overview
Implement management for the `~/.ssh/conf.d/` directory and configure the SSH client to include host-specific configurations from files within this directory. This ensures a modular and organized way to manage individual SSH host settings.

## Functional Requirements
- **Directory Creation**: Ensure the `~/.ssh/conf.d/` directory is created automatically if it does not exist.
- **Permissions Management**: Set strict permissions (`0700`) on the `~/.ssh/conf.d/` directory, ensuring it's owned by the user and inaccessible by others.
- **SSH Client Inclusion**: Configure `programs.ssh` in Home Manager to include all files directly within `~/.ssh/conf.d/` using the `Include` directive in the SSH client configuration.
- **Configuration Refactor**: Consolidate SSH settings by moving all options (e.g., `userKnownHostsFile`, `ForwardAgent`, etc.) into a single `matchBlocks."*"` block in the Home Manager `programs.ssh` configuration to ensure a unified host-wide default configuration.
- **SSH Agent Timeout**: Configure the `ssh-agent` service to automatically time out identities after 15 minutes of inactivity.

## Non-Functional Requirements
- **Security**: The `~/.ssh/conf.d/` directory and its contents must have appropriate secure permissions.
- **Modularity**: Allow users to easily add or remove host-specific SSH configurations by simply managing files within the `~/.ssh/conf.d/` directory.

## Acceptance Criteria
- [ ] The `~/.ssh/conf.d/` directory exists.
- [ ] The permissions of `~/.ssh/conf.d/` are `drwx------` (0700).
- [ ] The SSH client successfully parses and applies configurations from files placed in `~/.ssh/conf.d/`.
- [ ] Only files directly in `~/.ssh/conf.d/` are included, not those in subdirectories.

## Out of Scope
- Recursive inclusion of subdirectories within `~/.ssh/conf.d/`.
- Management of individual host configuration files within `~/.ssh/conf.d/`.