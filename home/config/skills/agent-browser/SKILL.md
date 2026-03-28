---
name: agent-browser
description: Expert in browser automation using the agent-browser CLI. Use when you need to navigate, interact with, or extract data from web pages.
---

# agent-browser

You are an expert in using `agent-browser`, a fast native CLI for headless browser automation.

## Core Workflow

1.  **Navigate**: `agent-browser open <url>`
2.  **Understand**: `agent-browser snapshot -i` (Get interactive elements with refs like `@e1`)
3.  **Interact**: `agent-browser click @e1`, `agent-browser fill @e2 "text"`, etc.
4.  **Verify**: Re-snapshot or `agent-browser screenshot` to confirm state.

## Essential Commands

- `agent-browser open <url>`: Navigate to a URL.
- `agent-browser snapshot -i`: Get accessibility tree with refs. **Always do this first to find elements.**
- `agent-browser click <ref|selector>`: Click an element.
- `agent-browser fill <ref|selector> <text>`: Clear and fill an input.
- `agent-browser type <ref|selector> <text>`: Type into an input.
- `agent-browser get text <ref|selector>`: Extract text.
- `agent-browser wait <selector|ms>`: Wait for element or time.
- `agent-browser screenshot [path]`: Take a screenshot for visual verification.
- `agent-browser screenshot --annotate`: Take a screenshot with numbered labels matching refs.

## Tips for Efficiency

- **Use Refs**: Always prefer `@e1`, `@e2` refs from `snapshot` over CSS selectors. They are faster and more deterministic.
- **Chain Commands**: Use `&&` to combine actions: `agent-browser open example.com && agent-browser wait --load networkidle && agent-browser snapshot -i`.
- **JSON Output**: Use `--json` if you need to parse structured data: `agent-browser snapshot -i --json`.
- **Interactive Mode**: Use `snapshot -i` to filter out non-interactive elements and reduce context usage.
- **Annotated Screenshots**: If you are unsure about an element's purpose, use `screenshot --annotate` to see visual labels.

## Troubleshooting

- If navigation fails with `net::ERR_NAME_NOT_RESOLVED`, verify connectivity with `ping`.
- The browser persists via a background daemon; `agent-browser close` ends the session.
