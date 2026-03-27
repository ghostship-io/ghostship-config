---
name: ssh
description: Use when managing remote servers via standard SSH and SCP commands. Includes instructions for file transfers, local editing preferences, and root access protocol.
category: devops
risk: high
source: workspace
date_added: "2026-03-27"
---

# SSH & Remote Management Expert

This skill provides instructions for managing remote servers using standard OpenSSH tools (`ssh`, `scp`) available in the local environment. It emphasizes a robust workflow for file editing and strict protocols for elevated access.

## Core Directives

### 1. Connecting to Servers
Use standard `ssh` commands to execute remote tasks. Leverage aliases defined in `~/.ssh/config` for simplicity.
- **Run Command**: `ssh <host> "<command>"`
- **Interactive Shell**: If you need to run multiple commands that depend on state (like `cd`), either chain them with `&&` or use a single `ssh` call with a heredoc.

### 2. File Transfer Workflow (Preference)
When you need to modify a file on a remote server, **ALWAYS** follow this preferred local-first workflow:
1.  **Download**: Use `scp` to copy the file from the server to your local workspace.
    - `scp <host>:/path/to/remote/file ./local_copy`
2.  **Modify**: Use local tools (like `replace` or `write_file`) to edit the file in your local workspace.
3.  **Upload**: Use `scp` to send the modified file back to the server.
    - `scp ./local_copy <host>:/path/to/remote/file`
4.  **Fix Permissions**: After uploading, ensure the file has the correct ownership and permissions on the remote server.
    - `ssh <host> "chmod <perms> /path/to/remote/file && chown <user>:<group> /path/to/remote/file"`

### 3. Root Access Protocol
If a task requires root privileges (e.g., modifying system files or managing services) and your current user does not have sufficient `sudo` rights or if interactive `sudo` is complex:
- **Protocol**: Stop and ask the user to create an "agentroot" tmux session on the target server.
- **Instruction to User**: "Please create a root tmux session on `<host>` using this command: `tmux new-session -s agentroot 'sudo -i' # ctrl+b d to disconnect`"

- **Usage**: Once the session is created, you can interact with it via `ssh <host> -t "tmux attach -t agentroot"`.

## Best Practices

- **Atomic Uploads**: When uploading critical config files, upload to a temporary location first (`/tmp/file.new`), then move it to the final destination in a single `ssh` command to minimize downtime or partial config states.
- **Verification**: Always verify changes on the remote server immediately after an upload (e.g., check file content with `cat` and service status with `systemctl status`).
- **SSH Config**: Assume `~/.ssh/config` is the source of truth for host aliases and connection parameters.
- **Error Handling**: Check the exit code of `ssh` and `scp` commands. A non-zero exit code indicates a failure that must be diagnosed.
