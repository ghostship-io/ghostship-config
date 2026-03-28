---
name: agent-browser
description: Expert in browser automation using the agent-browser CLI. Use when you need to navigate, interact with, or extract data from web pages.
---

# agent-browser

You are an expert in using `agent-browser`, a fast native CLI for headless browser automation. This tool is designed for AI agents to interact with the web efficiently.

> **Note**: For a complete and up-to-date list of all supported commands, subcommands, and options, run `agent-browser` without any arguments.

## Core Workflow

1.  **Navigate**: `agent-browser open <url>`
2.  **Understand**: `agent-browser snapshot -i` (Get interactive elements with refs like `@e1`)
3.  **Interact**: `agent-browser click @e1`, `agent-browser fill @e2 "text"`, etc.
4.  **Verify**: Re-snapshot or `agent-browser screenshot` to confirm state.

## Advanced Usage Patterns

### Efficient Discovery
Reduce context usage by filtering snapshots:
- `agent-browser snapshot -i`: Interactive elements only.
- `agent-browser snapshot -c`: Compact tree (no empty structural elements).
- `agent-browser snapshot -d <n>`: Limit tree depth.
- `agent-browser snapshot -s "<selector>"`: Scope to a specific CSS selector.

### Semantic Locators
Robust element selection when refs are insufficient:
- `agent-browser find role <role> <action> --name "<name>"` (e.g., `role button click --name "Submit"`)
- `agent-browser find label "<text>" <action>`
- `agent-browser find text "<text>" <action>`
- `agent-browser find placeholder "<text>" <action>`

### Waiting and Reliability
- `agent-browser wait --load networkidle`: Wait for network activity to settle.
- `agent-browser wait <selector> --state <attached|detached|visible|hidden>`: Precise element state waiting.
- `agent-browser wait --text "<text>"`: Wait for specific text to appear.

### Visual and Debugging Tools
- `agent-browser screenshot --annotate`: Overlays ref labels (@e1, @e2) on the image. Excellent for visual reasoning.
- `agent-browser console [--clear]`: View browser console logs.
- `agent-browser errors [--clear]`: View page errors.
- `agent-browser inspect`: Opens Chrome DevTools for the active page (useful in headed mode).

## Comprehensive Command Reference

### Browser and Sessions
- `agent-browser set viewport <w> <h>`: Change window size.
- `agent-browser session list`: List all active sessions.
- `agent-browser close --all`: Close every active session and the daemon.

### Storage and Network
- `agent-browser cookies [get|set|clear]`: Manage session cookies.
- `agent-browser storage <local|session>`: Manage web storage.
- `agent-browser network requests`: View recent network requests.
- `agent-browser network route <url> --abort`: Block specific network requests.

### Tabs and Navigation
- `agent-browser tab [new|list|close|<n>]`: Manage multiple tabs.
- `agent-browser back` / `forward` / `reload`: Standard history control.

### Authentication Vault
- `agent-browser auth save <name> --url <url> --username <user> --password <pass>`: Securely store credentials.
- `agent-browser auth login <name>`: Automatically fill login forms and authenticate.

### Observability Dashboard
- `agent-browser dashboard start`: Launch the live observability dashboard (default: port 4848).
- `agent-browser dashboard stop`: Stop the dashboard.

## Tips for AI Efficiency

1.  **Prefer Refs**: Always use `@e1` style refs from `snapshot`. They are deterministic and faster than re-querying the DOM.
2.  **Chain Actions**: Combine related steps using `&&`:
    `agent-browser open google.com && agent-browser wait --load networkidle && agent-browser snapshot -i`
3.  **Handle Popups**: Check for modals, cookie banners, or shadow DOM in a new `snapshot` if interactions fail.
4.  **Batch Mode**: For complex sequences, use `agent-browser batch` to pipe a JSON array of commands.
5.  **Headed Mode**: Use `--headed` if you need to visually debug an interaction.

## Troubleshooting

- **ERR_NAME_NOT_RESOLVED**: Verify connectivity. If in WSL, try `ping google.com`.
- **Action timed out**: The default timeout is 25s. Increase via `AGENT_BROWSER_DEFAULT_TIMEOUT` if necessary.
- **Ref expired**: If the page navigates significantly, take a new `snapshot` to get fresh refs.
