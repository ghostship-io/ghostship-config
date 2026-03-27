---
name: ssh
description: Use when managing remote servers via persistent SSH sessions. Supports stateful command execution (e.g., 'cd' persists), sudo handling, and SFTP file operations. Integrates with ~/.ssh/config.
category: devops
risk: medium
source: community
date_added: "2026-02-25"
---

# MCP SSH Session Agent

Expert in remote server management using `mcp-ssh-session`. This skill provides a specialized interface for controlling remote systems with persistent shell state, allowing directory changes and environment variables to persist across commands.

## Core Capabilities

- **Persistent Sessions**: SSH connections and shell state (cwd, env) are maintained across multiple tool calls.
- **Smart Execution**: Commands automatically transition to async mode if they exceed the initial timeout, preventing server hangs.
- **Async Operations**: Execute long-running tasks in the background with status tracking and interruption support.
- **Sudo & Network Support**: Built-in handling for `sudo` prompts and network device "enable" modes.
- **SFTP File Management**: High-performance file reading and writing with automatic sudo fallback for protected paths.

## Workflow: Connecting to Remote Servers

The agent leverages your **local SSH configuration**. Ensure target hosts are defined in `~/.ssh/config` for easy aliasing.

### 1. Execute Commands
Use `execute_command` for standard tasks. It is "smart" and will return a `command_id` if the task takes too long, allowing you to check status later.

### 2. Manage State
Since sessions are persistent, you can run `cd /path/to/project` in one call and subsequent calls to `execute_command` for the same `host` will remain in that directory.

### 3. File Operations
Use `read_file` and `write_file` for efficient transfers. They use SFTP by default but can use `sudo cat` or `sudo tee` if `use_sudo` is true.

## Tool Reference

### Command Execution
- **`execute_command`**: Run a command (synchronous with auto-async fallback).
- **`execute_command_async`**: Explicitly start a background task.
- **`get_command_status`**: Check progress and retrieve output of an async task.
- **`send_input`**: Provide input to interactive prompts (like sudo or confirmation).
- **`interrupt_command_by_id`**: Send Ctrl+C to a running task.

### Session & History
- **`list_sessions`**: See active persistent connections.
- **`close_session`**: Terminate a specific host connection.
- **`list_command_history`**: Review recent command results.

### File Management
- **`read_file`**: Read remote file content (SFTP with sudo fallback).
- **`write_file`**: Write remote file content (SFTP with sudo fallback).

## Best Practices

- **Use SSH Config**: Map complex connection details to simple aliases in `~/.ssh/config`.
- **Leverage Persistence**: Don't chain everything into one long shell string; use the persistence to your advantage.
- **Check Status**: For long-running builds or syncs, use async tools to avoid blocking the agent loop.
- **Sudo Handling**: Use the `sudo_password` or `use_sudo` (if NOPASSWD) parameters instead of manually typing passwords into `execute_command` strings.
