---
name: ssh
description: Expert in remote server management using @aiondadotcom/mcp-ssh. Provides specialized tools for interacting with remote systems through the Model Context Protocol (MCP) by leveraging your local SSH configuration. Use for remote command execution, file transfers, and system discovery on hosts defined in your ~/.ssh/config.
category: devops
risk: medium
source: community
date_added: "2026-02-25"
---

# MCP SSH Agent

Expert in remote server management using `@aiondadotcom/mcp-ssh`. This skill provides a specialized interface for controlling remote systems by leveraging your existing local SSH configuration and identity.

## Core Capabilities

- **Host Discovery**: Automatically identifies available remote systems from your `~/.ssh/config` and `~/.ssh/known_hosts`.
- **Remote Execution**: Run single or batch commands on remote hosts.
- **File Transfer**: Upload and download files between local and remote systems using `scp` under the hood.
- **Connectivity Monitoring**: Check the status and retrieve information about configured remote hosts.

## Workflow: Connecting to Remote Servers

The `mcp-ssh` agent relies on your **local SSH configuration**. Before using this skill, ensure the target host is defined in your `~/.ssh/config`.

### 1. Identify Hosts
Use `ssh-mcp_listKnownHosts` to see which servers the agent has discovered from your local configuration. Use the `hostAlias` (the `Host` entry in your config) for all subsequent tools.

### 2. Verify Connectivity
Before running complex tasks, use `ssh-mcp_checkConnectivity` to ensure the remote host is reachable and your authentication (keys/agent) is working.

## Tool Reference

### Remote Execution
- **`ssh-mcp_runRemoteCommand`**: Execute a single command on the remote host.
- **`ssh-mcp_runCommandBatch`**: Execute a sequence of commands on the remote host.
- **`ssh-mcp_getHostInfo`**: Retrieve basic system information from the remote host.

### File Management
- **`ssh-mcp_uploadFile`**: Transfer a file from your local machine to the remote host.
- **`ssh-mcp_downloadFile`**: Transfer a file from the remote host to your local machine.

## Best Practices

- **SSH Config First**: Manage your remote servers by adding `Host` entries to `~/.ssh/config`. The agent will automatically pick them up.
- **SSH Agent**: This agent relies on your local `ssh` and `scp` binaries. Ensure your SSH keys are loaded into your local `ssh-agent` for seamless, non-interactive authentication.
- **Absolute Paths**: When transferring files, prefer absolute paths for both `localPath` and `remotePath` to avoid ambiguity across different environments.
- **Batching**: Use `runCommandBatch` for multi-step procedures (e.g., updating a package and then restarting a service) to reduce round-trip overhead.
