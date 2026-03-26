# Unified Agent Tooling Overhaul Spec

## Overview
Unify Gemini, Conductor, OpenCode, and Codex around a consistent agent-tooling model. Shared skills, global instructions, plugins/extensions, and MCP servers should be managed centrally wherever possible, with `~/.agents` as the preferred home for reusable agent assets.

## Functional Requirements
- Use `~/.agents` as the canonical source for shared skills and global instructions where possible.
- Standardize how Gemini, OpenCode, Conductor, and Codex discover and load shared agent assets.
- Make Codex behave as consistently as possible with Gemini and OpenCode in installation, launch, and update flow.
- Add a lightweight pre-launch update check for Gemini, OpenCode, and Codex.
- If an update is available, automatically update first, then launch the CLI.
- For GitHub-backed plugins and extensions, compare the installed revision to the remote `HEAD` and only refresh when the revision changes.
- Ensure Codex has the same extensions/plugins and MCP server configuration model as the other CLIs.
- Add a Gemini-delegation MCP server to Gemini, OpenCode, and Codex so the assistants can hand off repo research and plan-generation tasks to local Gemini CLI.
- Refresh MCP server configuration whenever `nh os switch` runs.
- Keep the launch experience simple and avoid extra manual steps.

## Non-Functional Requirements
- Changes should be centralized and maintainable.
- Startup overhead from update checks should stay minimal.
- The solution should survive rebuilds and remain consistent across hosts.

## Acceptance Criteria
- Gemini, OpenCode, and Codex all use the same shared skills/instructions source where applicable.
- Gemini, OpenCode, and Codex all run a pre-launch update check and auto-update when needed.
- Gemini and OpenCode only refresh GitHub-backed plugins/extensions when the remote revision changes.
- Codex is installed and launched through the same behavioral pattern as Gemini and OpenCode, with consistent wrapper behavior.
- Codex has the same MCP servers and extension/plugin behavior as the other CLIs.
- Gemini, OpenCode, and Codex all expose a Gemini-delegation MCP server for repo research and planning tasks.
- Running `nh os switch` refreshes MCP server configuration automatically.
- The resulting UX is consistent across the supported agent CLIs.

## Out of Scope
- Rewriting the actual content of individual skills unless needed for shared loading.
- Changing MCP server implementations themselves unless required for parity.
- Refactoring unrelated NixOS modules or host-specific configuration.
