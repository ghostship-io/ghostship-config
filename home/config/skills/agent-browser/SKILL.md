---
name: agent-browser
description: Expert in browser automation using the agent-browser CLI. Use when you need to navigate, interact with, or extract data from web pages.
---

# agent-browser

You are an expert in using `agent-browser`, a fast native CLI for headless browser automation. This tool is designed for AI agents to interact with the web efficiently.

## Core Workflow

1.  **Navigate**: `agent-browser open <url>`
2.  **Understand**: `agent-browser snapshot -i` (Get interactive elements with refs like `@e1`)
3.  **Interact**: `agent-browser click @e1`, `agent-browser fill @e2 "text"`, etc.
4.  **Verify**: Re-snapshot or `agent-browser screenshot` to confirm state.

## Advanced Usage Patterns

### Efficient Discovery
Instead of a full snapshot, use filters to reduce context:
- `agent-browser snapshot -i`: Only interactive elements (buttons, links, inputs).
- `agent-browser snapshot -c`: Compact tree (removes empty structural elements).
- `agent-browser snapshot -d 3`: Limit depth to 3 levels.
- `agent-browser snapshot -s "#main"`: Scope to a specific CSS selector.

### Semantic Locators
When refs aren't enough or you want more robust selection:
- `agent-browser find role button click --name "Submit"`
- `agent-browser find label "Email" fill "user@example.com"`
- `agent-browser find text "Sign In" click`

### Waiting for State
Always wait for the page to be ready to avoid flakiness:
- `agent-browser wait --load networkidle`: Wait for network to settle.
- `agent-browser wait "#results"`: Wait for a specific element to appear.
- `agent-browser wait --text "Success"`: Wait for specific text.

### Visual Reasoning
For complex layouts or icon-only buttons:
- `agent-browser screenshot --annotate`: Overlays refs (@e1, @e2) directly on the image. Use this if the text snapshot is ambiguous.

## Command Reference

### Navigation & State
- `open <url>`: Navigate to URL.
- `back` / `forward` / `reload`: Standard browser navigation.
- `get url` / `get title`: Current page info.
- `close`: Ends the current session and shuts down the daemon.

### Interaction
- `click <ref|sel>`: Click an element.
- `fill <ref|sel> <text>`: Clear and fill an input.
- `type <ref|sel> <text>`: Type text into an element.
- `press <key>`: Press a keyboard key (e.g., `Enter`, `Tab`).
- `hover <ref|sel>`: Move mouse to element.
- `select <ref|sel> <value>`: Select from a dropdown.
- `check` / `uncheck <ref|sel>`: Toggle checkboxes/radio buttons.

### Information Extraction
- `get text <ref|sel>`: Get inner text.
- `get value <ref|sel>`: Get input value.
- `get html <ref|sel>`: Get outer HTML.
- `get attr <ref|sel> <name>`: Get a specific attribute.

### Debugging & Tools
- `console`: View browser console logs.
- `errors`: View page errors.
- `eval <js>`: Execute arbitrary JavaScript in the page context.
- `cookies [get|clear]`: Manage session cookies.

## Tips for AI Efficiency

1.  **Prefer Refs**: Always use `@e1` style refs from `snapshot`. They are deterministic and faster than re-querying the DOM.
2.  **Chain Actions**: Combine related steps using `&&` to reduce tool turns:
    `agent-browser open google.com && agent-browser wait --load networkidle && agent-browser snapshot -i`
3.  **Handle Popups**: If a command seems to "do nothing," check for modals or cookie banners in a new `snapshot`.
4.  **Use JSON**: Add `--json` to any command for structured output that is easier to parse.
5.  **Session Persistence**: The browser stays open in the background until you call `agent-browser close`. You can run multiple tool calls against the same session.

## Troubleshooting

- **ERR_NAME_NOT_RESOLVED**: Check connectivity. If in WSL, try `ping google.com`.
- **Element not found**: Ensure the element is visible. Use `agent-browser wait <selector>` if needed.
- **Action timed out**: The default timeout is 25s. If a page is very slow, you may need to wait explicitly for a load state.
- **Ref expired**: If the page navigates or reloads significantly, old refs (@e1) may become invalid. Take a new `snapshot`.
