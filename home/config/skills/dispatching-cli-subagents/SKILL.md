---
name: dispatching-cli-subagents
description: Use whenever you want to spawn, delegate to, or dispatch a subagent or another CLI agent (gemini, codex, opencode)
---

# Dispatching CLI Subagents

## Overview
When you need to delegate work to another agent, you must execute them as a non-interactive (headless) CLI process. This skill defines the universal rules and command syntaxes for safely spawning `gemini`, `codex`, and `opencode` sub-agents, managing their models, and performing high-value system tasks via `stdout`.

## Core Rules for Spawning Sub-agents
1. **Bypass Interactive Prompts:** You MUST use flags like `--yolo`, `--full-auto`, or `-p`. Failing to do so will cause the sub-agent to freeze forever waiting for human input.
2. **Bundle Complete Context:** Headless sub-agents do not inherit your session history. Pass all necessary context via the prompt string, shell pipes, or file attachments.
3. **Explicit Checklists:** Always give the sub-agent clear physical exit criteria (e.g., "Do not finish until tests pass").
4. **Scoping:** Use directory flags (e.g., `--include-directories`, `-C`) to focus the sub-agent on exactly what it needs to see.

## Tool Reference & Advanced Orchestration

### Gemini CLI (`gemini`)
Optimized for zero-shot reasoning, architectural analysis, and security auditing.
* **Non-interactive execution:** Use `-p <prompt>` or `--prompt <prompt>`.
* **Approval & Safety (Automation):**
  * **`--yolo`** or **`-y`**: Automatically accept all actions (Use for fully autonomous subagents).
  * **Plan Mode (Read-only):** Use `--approval-mode plan`. No edits allowed.
* **Context & Scope:**
  * **`--include-directories <paths>`**: Add extra directories to the subagent's workspace.
  * **`-e <extension>`**: Use only specific extensions (e.g., `-e security`).
* **JSON Mode:** Use `-o json` or `--output-format json` for a structured response on `stdout`.

### Codex CLI (`codex`)
Optimized for multi-step engineering, autonomous file modification, and CI/CD automation.
* **Non-interactive execution:** Use the `exec` subcommand.
* **Automation & Safety:**
  * **`--full-auto`**: Convenience alias for `-a on-request --sandbox workspace-write`.
  * **Plan Mode (Read-only):** Use `--sandbox read-only`.
  * **`-a never`**: Never ask for approval. Failures are returned to the model as text.
* **JSON & Structured Data:**
  * **`--json` (JSONL Mode):** Streams execution events (thread start, tool calls, file changes, reasoning, and final response) as JSON Lines (JSONL) on `stdout`.
* **Advanced Orchestration:**
  * **`--ephemeral`**: Prevents saving session history files to disk.
  * **`--skip-git-repo-check`**: Allow running outside a Git repository.
* **Authentication (CI/Headless):** Use the `CODEX_API_KEY` environment variable.

### OpenCode AI (`opencode`)
Optimized for specific model targeting and speculative engineering.
* **Non-interactive execution:** Use the `run` subcommand with `--quiet`.
* **Automation & Safety:**
  * **Plan Mode (Read-only):** Use the `--plan` flag. Focuses on strategy without modification.
* **JSON Mode:** Use `--format json` for a structured response on `stdout`.
* **Speculative Engineering:**
  * **`--fork`**: Fork the previous session to test multiple approaches in parallel.
  * **`-c`** or **`--continue`**: Continue the last session to build upon previous work.

## Machine-Readable Communication
When spawning a sub-agent to return data to you (the orchestrator), use JSON output formats to ensure reliable parsing via `stdout`.

### Pattern: Parsing Codex JSONL Stream
If you need to monitor progress or capture specific tool calls, pipe the `--json` output to `jq`:
```bash
# Capture the final agent message from the JSONL stream without creating files
codex exec --json "Analyze this code" | jq 'select(.type == "item.completed" and .item.type == "agent_message") | .item.text'
```

### Pattern: Extraction via Gemini
```bash
# Capture structured results directly from stdout
gemini -o json -p "Extract all TODOs from @src/ and return as a JSON list"
```

## High-Value Orchestration Patterns

### Pattern: Codebase-Wide Analysis (Gemini)
Use Gemini for system-level understanding without modifying files.
```bash
gemini -p "Analyze the entire codebase at @. and provide a comprehensive description of the architecture."
```

### Pattern: Automated Security Review (Gemini)
Run the security extension headlessly and review findings.
```bash
gemini -p "/security:analyze"
```

### Pattern: The Autonomous Implementer (Codex)
Dispatch Codex for surgical implementation tasks with broad permissions.
```bash
codex exec --full-auto --sandbox workspace-write "Implement the requested feature. Run tests to verify."
```

### Pattern: Spec Reviewer (Piping Pattern)
Delegate code review to a fast model via piping files into the prompt.
```bash
cat changed_file.ts spec.md | gemini -m pro -p "Does the code satisfy all requirements in the spec? Answer YES or list missing requirements."
```

## Common Mistakes
* **Hanging Processes:** Forgetting automation flags like `--yolo`, `--full-auto`, or `-a never`.
* **Context Starvation:** Not using `--include-directories` or `-C` when the task is outside the current root.
* **Model Selection:** Using a paid model with `opencode` (**MUST USE FREE ONLY**).
* **Parsing Noise:** Not using `--quiet` (OpenCode) or machine-readable flags (`-o json`, `--json`).
* **File Output:** Using file-based output flags when `stdout` parsing via JSON is more efficient and cleaner for ephemeral sub-agents.
