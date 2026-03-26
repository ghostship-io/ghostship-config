# Implementation Plan - Playwright MCP Integration for Gemini

## Phase 1: Package Installation & Environment Configuration [checkpoint: e97c61a]
- [x] Task: Update `home/nixos.nix` to install Playwright packages. 087513f
    - [x] Add `pkgs.playwright-driver.browsers` and `pkgs.playwright-mcp` to `home.packages`.
- [x] Task: Configure Playwright environment variables in `home/nixos.nix`. 087513f
    - [x] Set `PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}"`.
    - [x] Set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1"`.
- [x] Task: Conductor - User Manual Verification 'Package Installation & Environment Configuration' (Protocol in workflow.md) e97c61a

## Phase 2: Gemini CLI Integration [checkpoint: dce16dc]
- [x] Task: Update Gemini CLI settings in `home/nixos.nix`. 7fb96da
    - [x] Add `mcpServers` block to `home.file.".gemini/settings.json"`.
    - [x] Configure `playwright` MCP server with `command: "mcp-server-playwright"` and `args: []`.
- [x] Task: Conductor - User Manual Verification 'Gemini CLI Integration' (Protocol in workflow.md) dce16dc

## Phase 3: Validation & Testing [checkpoint: 9ddfff2]
- [x] Task: Verify integration and browser access. 9ddfff2
    - [x] Apply changes with `nh home switch`.
    - [x] Run a test command via Gemini CLI to verify browser navigation.
- [x] Task: Conductor - User Manual Verification 'Validation & Testing' (Protocol in workflow.md) 9ddfff2
