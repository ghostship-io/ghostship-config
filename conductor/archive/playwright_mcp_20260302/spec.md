# Specification: Playwright MCP Integration for Gemini

## Overview
Integrate the Playwright Model Context Protocol (MCP) server into the Gemini CLI environment for the `nixos` user. This enables Gemini to interact with a web browser (Chromium) to perform research, testing, and other web-based tasks directly from the CLI.

## Functional Requirements
1.  **Browser Availability**: Ensure Chromium and the Playwright driver are available in the `nixos` user environment on NixOS.
2.  **MCP Integration**: Configure Gemini CLI to recognize and utilize the Playwright MCP server.
3.  **On-Demand Execution**: The MCP server should be started by Gemini CLI only when needed (configured via `mcpServers`).
4.  **Persistent Configuration**: Manage the integration declaratively via Home Manager.

## Technical Implementation
1.  **Package Installation**:
    - Add `pkgs.playwright-driver.browsers` and `pkgs.playwright-mcp` to `home.packages` in `home/nixos.nix`.
2.  **Environment Variables**:
    - Set `PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}"` in `home.sessionVariables`.
    - Set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"` in `home.sessionVariables`.
3.  **Gemini Configuration**:
    - Update `home.file.".gemini/settings.json"` in `home/nixos.nix` to include:
      ```json
      "mcpServers": {
        "playwright": {
          "command": "mcp-server-playwright",
          "args": []
        }
      }
      ```

## Acceptance Criteria
- [ ] Gemini CLI reports "playwright" as a connected MCP server (if supported by CLI logging/status).
- [ ] Gemini can successfully open a browser and navigate to a URL (verified via a test prompt like "Open google.com and tell me the title").
- [ ] No browser downloads are triggered during runtime; Nix-provided binaries are used.

## Out of Scope
- System-wide Playwright installation for all users.
- Persistent systemd service for the MCP server (it will be started on-demand).
- Integration with Firefox or WebKit (Chromium only for this track).
