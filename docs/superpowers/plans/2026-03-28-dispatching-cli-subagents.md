# Implementation Plan: Universal Sub-agent Dispatch Skill

## Objective
Create a universally available agent skill (`dispatching-cli-subagents`) that teaches any agent on the system how to properly spawn and delegate tasks to sub-agents (`gemini`, `codex`, and `opencode`). This ensures consistent non-interactive execution, correct model selection, and adherence to system-wide constraints (such as exclusively using free models for `opencode`).

## Key Files & Context
- **Target File:** `/home/nixos/nixos-config/home/config/skills/dispatching-cli-subagents/SKILL.md`

## Implementation Steps
1. Create the `dispatching-cli-subagents` directory.
2. Write the following `SKILL.md` file:

```markdown
---
name: dispatching-cli-subagents
description: Use whenever you want to spawn, delegate to, or dispatch a subagent or another CLI agent (gemini, codex, opencode)
---

# Dispatching CLI Subagents

## Overview
When you need to delegate work to another agent, you must execute them as a non-interactive (headless) CLI process. This skill defines the universal rules and command syntaxes for safely spawning `gemini`, `codex`, and `opencode` sub-agents.

## Core Rules for Spawning Sub-agents

1. **Bypass Interactive Prompts:** You MUST use flags like `--full-auto`, `--quiet`, or `-p`. Failing to do so will cause the sub-agent to freeze forever waiting for human input.
2. **Bundle Complete Context:** Headless sub-agents do not inherit your session history. Pass all necessary context via the prompt string, shell pipes, or file attachments.
3. **Explicit Checklists:** Always give the sub-agent clear physical exit criteria (e.g., "Do not finish until tests pass").

## Tool Reference & Model Constraints

### 1. OpenCode AI (`opencode`)
Optimized for specific model targeting and one-shot programmatic fixes.
*   **CRITICAL CONSTRAINT:** You MUST ONLY use **free models** when dispatching `opencode`. Do not use any paid or proprietary models.
*   **Non-interactive execution:** Use the `run` subcommand.
    ```bash
    opencode run "Refactor src/utils.ts to use async/await" --quiet
    ```
*   **Model Selection (Free Models Only):** 
    *   `opencode run --model google/gemini-2.5-flash "..."`
    *   `opencode run --model google/gemini-2.0-flash-exp "..."`
*   **Important Flags:**
    *   `--quiet` or `-q`: Suppresses terminal animations.
    *   `--format json`: Forces structured JSON output.

### 2. Gemini CLI (`gemini`)
Optimized for zero-shot text and code reasoning tasks, summarization, and quick answers.
*   **Non-interactive execution:** Use the `-p` (prompt) flag.
    ```bash
    gemini -p "Review this implementation plan for edge cases"
    cat data.json | gemini -p "Summarize these findings"
    ```
*   **Model Selection:** Use the `-m` (or `--model`) flag.
    *   `gemini -m flash -p "..."`
    *   `gemini -m pro -p "..."`

### 3. Codex (`codex`)
Optimized for multi-step software engineering, autonomous file modification, and command execution.
*   **Non-interactive execution:** Use the `exec` subcommand with `--full-auto`.
    ```bash
    codex exec --full-auto "Implement the changes described in plan.md"
    ```
*   **Important Flags:**
    *   `--full-auto`: Allows reading/writing without prompts (**CRITICAL**).
    *   `--json`: Outputs session as JSON lines stream.

## Common Patterns
### Pattern: The Spec Reviewer
Delegate code review to a fast model via piping:
```bash
cat changed_file.ts spec.md | gemini -m pro -p "Does the code satisfy all requirements in the spec? Answer YES or list missing requirements."
```
### Pattern: The Autonomous Implementer
Dispatch a full-auto engineering agent to handle a well-defined task:
```bash
codex exec --full-auto "Read task_1.md and implement the requested feature. Run tests to verify."
```
```
