---
name: dispatching-cli-subagents
description: Use whenever you want to spawn, delegate to, or dispatch a subagent or another CLI agent (gemini, codex, opencode)
---

# Dispatching CLI Subagents

## Overview
When you need to delegate work to another agent, you must execute them as a non-interactive (headless) CLI process. This skill defines the universal rules and command syntaxes for safely spawning `gemini`, `codex`, and `opencode` sub-agents, managing their roles, and performing high-value system tasks via `stdout`.

## Core Rules for Spawning Sub-agents
1. **Bypass Interactive Prompts:** You MUST use flags like `--yolo`, `--full-auto`, or `-p`. Failing to do so will cause the sub-agent to freeze forever waiting for human input.
2. **Bundle Complete Context:** Headless sub-agents do not inherit your session history. Pass all necessary context via the prompt string, shell pipes, or file attachments.
3. **Explicit Checklists:** Always give the sub-agent clear physical exit criteria (e.g., "Do not finish until tests pass").
4. **Scoping:** Use directory flags (e.g., `--include-directories`, `-C`) to focus the sub-agent on exactly what it needs to see.

## Available CLI Subagents & Roles

### Gemini CLI (`gemini`)
Optimized for zero-shot reasoning, architectural analysis, and extension-based auditing.
* **Available Roles/Extensions:**
  - **Security Auditor:** Uses the `gemini-cli-security` extension for automated vulnerability scanning.
  - **Superpowers:** Uses the `superpowers` extension for advanced planning and execution patterns.
* **Orchestration Patterns:**
  - **Automated Security Review:** `gemini -p "/security:analyze"` (scans for vulnerabilities).
  - **Codebase Discovery:** `gemini -p "Analyze the architecture of @src/ and report dependencies."`
* **Key Flags:**
  - `-p <prompt>`: Non-interactive execution.
  - `-y`, `--yolo`: Automatically accept all actions.
  - `--approval-mode plan`: Read-only mode.
  - `-e <extension>`: Enable specific extensions only.
  - `-o json`: Structured output on `stdout`.

### Codex CLI (`codex`)
Optimized for multi-step engineering, autonomous file modification, and code reviews.
* **Available Roles/Specialized Commands:**
  - **General Implementer (`exec`):** The default role for executing complex engineering tasks.
  - **Code Reviewer (`review`):** Specialized for auditing changes against a base branch or commit.
* **Orchestration Patterns:**
  - **Non-Interactive Review:** `codex review --uncommitted` (reviews staged/unstaged changes).
  - **Base-Branch Review:** `codex review --base main` (reviews diff against main).
  - **Autonomous Feature Work:** `codex exec --full-auto "Implement the feature described in spec.md"`
* **Key Flags:**
  - `--full-auto`: Convenience for `-a on-request --sandbox workspace-write`.
  - `-s <mode>`: Sandbox selection (`read-only`, `workspace-write`, `danger-full-access`).
  - `-a <policy>`: Approval policy (`never`, `on-request`).
  - `--json`: Stream execution events as JSONL.

### OpenCode AI (`opencode`)
Optimized for role-based execution using specialized internal agents and GitHub integration.
* **Available Internal Agents:**
  - **`explore`**: Optimized for codebase navigation and discovery.
  - **`plan`**: Focused on creating comprehensive implementation strategies.
  - **`build`**: The primary agent for executing code changes.
  - **`summary`**: Specialized in condensing complex logs or code into brief reports.
  - **`title`**: Generates concise titles for tasks or commits.
  - **`general`**: A balanced agent for standard tasks.
  - **`compaction`**: Used for session state management and summary.
* **Specialized Workflows:**
  - **GitHub Agent:** `opencode github run` (handles GitHub-specific workflows).
  - **PR Agent:** `opencode pr <number>` (checks out a PR and initiates an investigation session).
* **Orchestration Patterns:**
  - **Research Session:** `opencode run --agent explore "Find all occurrences of secret management patterns."`
  - **Strategy Phase:** `opencode run --agent plan "Develop a migration plan for the frontend to React 19."`
  - **Quick Summary:** `cat log.txt | opencode run --agent summary`
* **Key Flags:**
  - `--agent <name>`: Explicitly select one of the roles listed above.
  - `-c`, `--continue`: Resume the previous session.
  - `--fork`: Test a new approach based on the existing session state.
  - `--format json`: Structured response for parsing.

## High-Value Orchestration Patterns (Cross-Utility)

### Pattern: The "Double-Check" Review
Spawning a fast reviewer to audit a complex implementation before finalization.
```bash
# Get the current diff and pipe it to a reviewer role
git diff HEAD | opencode run --agent summary "Summarize these changes and highlight potential risks."
```

### Pattern: Extraction via Gemini
```bash
# Capture structured results directly from stdout
gemini -o json -p "Extract all TODOs from @src/ and return as a JSON list"
```

### Pattern: CI/CD Security Gate
```bash
# Fail build if critical vulnerabilities are found (conceptual)
gemini -p "/security:analyze" -o json | jq -e '.vulnerabilities | any(.severity == "Critical")' && exit 1
```

## Common Mistakes
* **Hanging Processes:** Forgetting automation flags like `--yolo`, `--full-auto`, or `-a never`.
* **Context Starvation:** Not using `--include-directories` (Gemini) or `-C` (Codex) when the task is outside the current root.
* **Role Mismatch:** Using `build` (OpenCode) for simple discovery when `explore` is faster and safer.
* **Parsing Noise:** Not using machine-readable flags (`-o json`, `--json`, `--format json`).
