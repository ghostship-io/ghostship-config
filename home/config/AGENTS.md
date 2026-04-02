# Agent Directives: Unified NixOS Configuration

## 1. Core Directives (The Ground Rules)

### Memory & Persistence
- **Primary Store**: ALWAYS use the project-level `AGENTS.md` as the primary memory and persistent fact store for the current workspace.
- **Continuous Learning (CRITICAL/HIGH PRIORITY)**: You MUST update the project's `AGENTS.md` whenever you hallucinate, get something wrong, or figure out something you didn't previously know. Record these in `## Lessons Learned` or `## Agent Added Memories` immediately to prevent repeating mistakes and to persist new discoveries.
- **Save Memory**: NEVER use the `save_memory` tool; cross-project memory is centrally managed. If you identify a global fact or preference to persist, inform the user exactly what to add to their global memory.

### Interaction Protocol
- **Brevity**: Provide commands first, followed by concise technical rationale.
- **Clarify Ambiguity**: Proactively ask targeted questions for any ambiguities or critical underspecified requirements.
- **Documentation First**: Maintenance of README, CHANGELOG, and Security files is as important as the code itself.

## 2. Development Workflow

### Task Initialization
- **Sync**: Before starting, ensure your local state matches the remote (if applicable).
- **Research**: Perform empirical research to validate the current state and task requirements.
- **Planning Artifacts**: Keep active spec-driven planning artifacts in the repo-local `openspec/` tree so every supported CLI agent can share the same workflow context.

### Implementation & Testing
- **Implementation**: Write high-quality, idiomatic code.
- **Verification**: ALWAYS attempt to verify your work yourself using available tools (SSH, `lsblk`, `nix-store`, etc.). Only ask the user to run things if you physically cannot (e.g., hardware verification).

### OSS Maintenance & Documentation
- **Identity**: Update `README.md` if functionality, setup, or usage examples have changed.
- **Continuous Learning**: Update project `AGENTS.md` with any new findings or mistake corrections immediately.

### Git Check-in
- **Git Hygiene**: Perform frequent, logical commits. Use the standard format: `<type>(<scope>): <description>`.
- **Changelog**: Update `CHANGELOG.md` with a curated summary of your changes.

## 3. Open Source Excellence

Treat EVERY repository as a potential high-quality open-source project.

- **Ownership**: You are SOLELY RESPONSIBLE for setting up and **continuously maintaining** the repository's identity, versioning, and security posture.
- **Maintenance**: You MUST proactively update `README.md`, `CHANGELOG.md`, `LICENSE`, `SECURITY.md`, and all GitHub metadata files (`.github/`) with EVERY relevant change.
- **Required Files**: Every repo MUST include: `README.md`, `LICENSE` (MIT default), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`.
- **Security Posture**: Maintain `SECURITY.md` and ensure no secrets or vulnerabilities are introduced.

## 4. Engineering Standards

### File & System Inspection
- **File Reading**: NEVER use `cat`. Always use the `read_file` tool for surgical or full-file inspection.
- **Verification Policy**: Validation is the only path to finality. ALWAYS attempt to verify state using tools (SSH, `lsblk`, `nix-store`, etc.). Empirically confirm state (kernel params, FS types, etc.) in the target environment.

### Execution Standards
- **Non-Interactive**: Always use non-interactive flags (e.g., `-y`, `--yes`, `--no-pager`) and environment variables (e.g., `CI=true`, `PAGER=cat`).
- **Shell Syntax**: All shell snippets must be valid **Fish** syntax (e.g., `set -x VAR val`, `; and`, `^/dev/null`).

## 5. Ecosystem & Language Standards

### NixOS & System Management
- **Environment**: ALWAYS use **Nix Flakes** and **`direnv`** for seamless activation.
- **Management**: Use native Nix commands for system management: `nix`, `nixos-rebuild`, and `switch-to-configuration`. Do not use `nh`.
- **One-off**: Use **`,` (comma)** for ephemeral execution of utilities.

### Browsing & Web Research
- **agent-browser**: Use this CLI when you need browser automation or web navigation. Run `agent-browser` by itself to inspect the command surface. Do not assume this repo provides a shared `agent-browser` skill.

### Python (Gold Standard)
- **Layout**: ALWAYS use the **`src/` layout** to prevent accidental imports and ensure testing against the installed package.
- **Config**: Use **`pyproject.toml`** (PEP 621) with a modern backend like `hatchling`.
- **Tooling**: Use **`uv`** (deps/env), **`ruff`** (lint/format), and **`mypy`** (strict typing).
- **Artifacts**: Include `uv.lock`, `.python-version`, and a `py.typed` marker.
