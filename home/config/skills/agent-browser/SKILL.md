---
name: agent-browser
description: Use when you need to perform headless browser automation, including navigating pages, interacting with elements, bypassing CAPTCHAs, or systematically crawling documentation.
---

# agent-browser

Expert guidance for using `agent-browser`, a fast native CLI for headless browser automation.

## Core Interaction Patterns

### 1. The "@ref" Pattern (Recommended)
Always prefer using the generated refs from a snapshot. They are the most robust and context-efficient way to interact.
- **Get Refs**: `agent-browser snapshot -i`
- **Click**: `agent-browser click @e1`
- **Fill**: `agent-browser fill @e2 "my search term"`
- **Focus**: `agent-browser focus @e3`

### 2. Semantic Selection
When you need to find an element without a ref or across page refreshes:
- **By Role and Name**: `agent-browser find role button click --name "Submit"`
- **By Text Content**: `agent-browser find text "Accept All" click`
- **By Placeholder**: `agent-browser find placeholder "Search documentation..." fill "nixos-rebuild"`
- **By Label**: `agent-browser find label "Username" type "myuser"`

### 3. Verification & Vision
Always verify the state of the page after an interaction:
- **Annotated Screenshot**: `agent-browser screenshot --annotate` (Labels elements with their @refs visually)
- **Get State**: `agent-browser get url`, `agent-browser get title`
- **Check Visibility**: `agent-browser is visible "@e1"`

## Bypassing Protections (Cloudflare, reCAPTCHA)

To bypass modern bot detection, use the following techniques:

### 1. Anti-Detection Flags
Always start with flags that hide automation markers. You must close the daemon before changing args.
`agent-browser close --all && agent-browser --args "--no-sandbox,--disable-blink-features=AutomationControlled" open <url>`

### 2. Profile Persistence
Cloudflare often trusts established sessions. Use a persistent profile to save cookies and local storage:
`agent-browser --profile ~/.browser-sessions/docs open <url>`

### 3. Patient Waiting
Many "managed challenges" (Cloudflare Turnstile) auto-solve if the agent remains still for 5-10 seconds.
`agent-browser open <url> && agent-browser wait 10000 && agent-browser snapshot -i`

### 4. Targeting Iframes
CAPTCHAs often live in iframes. If `@ref` is missing in `snapshot -i`, use the `find` command to target the frame:
`agent-browser find role Iframe click --name "reCAPTCHA"`
`agent-browser find role Iframe click --name "Widget containing a Cloudflare security challenge"`

## Systematic Documentation Crawling

When an agent needs to "read the manual," follow this systematic pattern:

### 1. Map the Structure
Identify the navigation or sidebar container:
`agent-browser open <root_url> && agent-browser snapshot -s "nav, .sidebar, .toc"`

### 2. Extract Links
Collect refs for all documentation links in that scope:
`agent-browser snapshot -i -s ".sidebar"`

### 3. Sequential Processing
Visit links one by one. Do NOT open multiple tabs unless necessary, to conserve memory/context.
`agent-browser click @e5 && agent-browser wait --load networkidle && agent-browser snapshot -c`

### 4. State Management
Maintain a list of "visited" URLs in your internal memory to avoid infinite loops or re-reading the same page.

## Troubleshooting

- **"Daemon already running"**: Use `agent-browser close --all` before changing `--args` or `--engine`.
- **Element Not Found**: Ensure the page has fully loaded. Use `agent-browser wait --load networkidle` or `agent-browser wait 5000`.
- **Ref Expired**: Navigation or DOM updates invalidate refs. Take a fresh `snapshot` after any action that changes the page.
- **Shadow DOM**: If an element is visible but not in the snapshot, try a more specific selector with `snapshot -s`.
