---
name: ssh
description: Use for remote host work over ssh or scp, especially when a task needs remote commands, file transfer, or root-shell guidance.
---

# ssh

Use this skill when the work happens on another host.

## Core workflow

- Prefer `ssh <host> '<command>'` for targeted remote commands.
- For file edits, download with `scp`, edit locally, upload back, then verify on
  the remote host.
- For privileged remote work, use a root shell or a direct root SSH host. Do
  not recommend `sudo`.
- Verify the final remote state after uploads, restarts, or deploy steps.

## Read when needed

- [interactive SSH command patterns](references/interactive-commands.md) for
  shells, REPLs, prompts, and full-screen terminal tools on a remote host.
- [tmux background patterns](references/tmux-background.md) for common ways to
  launch, inspect, and reattach long-running remote work.
