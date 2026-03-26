# Gemini CLI: Master Directives & Workflow

## 1. Core Directives (The Ground Rules)

### Memory & Persistence
- **Primary Store**: ALWAYS use the project-level `GEMINI.md` as the primary memory and persistent fact store for the current workspace.
- **Continuous Learning (CRITICAL/HIGH PRIORITY)**: You MUST update the project's `GEMINI.md` whenever you hallucinate, get something wrong, or figure out something you didn't previously know. Record these in `## Lessons Learned` or `## Gemini Added Memories` immediately to prevent repeating mistakes and to persist new discoveries.
- **Save Memory**: NEVER use the `save_memory` tool; cross-project memory is centrally managed. If you identify a global fact or preference to persist, inform the user exactly what to add to their global memory.

### Interaction Protocol
- **Brevity**: Provide commands first, followed by concise technical rationale.
- **Clarify Ambiguity**: Proactively ask targeted questions for any ambiguities or critical underspecified requirements.
- **Documentation First**: Maintenance of README, CHANGELOG, and Security files is as important as the code itself.

## 2. Unified Development Workflow (Conductor & Git)
You MUST follow this strict, iterative workflow for every task. This process integrates Conductor task management with OSS maintenance and Git hygiene.

### Phase 0: Repository Setup (Conductor & OSS)
- **Workflow Alignment**: When setting up a new repository with Conductor, you MUST initialize `conductor/workflow.md` by copying the global template from `~/.gemini/workflow.md` and then customizing it for the project.
- **Identity & Baseline**: Initialize the mandatory OSS baseline immediately:
    - **`README.md`**: Create with a high-impact header, AI-Friendly TL;DR, 3-step Quick Start, and Status Badges.
    - **`LICENSE`**: Create an MIT license file.
    - **`CHANGELOG.md`**: Initialize with a "Initial Release" entry.
    - **`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`**: Bootstrap with standard professional templates.
    - **Versioning**: Create the initial version file (`VERSION`, `package.json`, or `pyproject.toml`) at `0.1.0`.
- **GitHub Metadata**: Setup `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md`.

### Phase 1: Task Initialization
- **Sync**: Before starting, ensure your local state matches the remote (if applicable).
- **Conductor**: Select the next task from `plan.md` and mark it in-progress `[~]`.
- **Research**: Perform empirical research to validate the current state and task requirements.

### Phase 2: Implementation & Testing
- **Implementation**: Write high-quality, idiomatic code. 
- **TDD/Verification**: 
    - **Apps**: Implement unit/integration tests. If missing, ask the user to help set them up.
    - **Infra/Config**: Use test environments (VMs, dry-runs) for verification.
- **Autonomous Validation**: ALWAYS attempt to verify your work yourself. Only ask the user to run things if you physically cannot (e.g., hardware verification).

### Phase 3: OSS Maintenance & Documentation (MANDATORY)
- **Identity**: Update `README.md` if functionality, setup, or usage examples have changed. Ensure the **AI-Friendly TL;DR** is accurate.
- **Security**: Update `SECURITY.md` or security-related documentation if you've added/changed sensitive boundaries.
- **Continuous Learning**: Update project `GEMINI.md` with any new findings or mistake corrections immediately.

### Phase 4: Git Check-in & Versioning
- **Git Hygiene**: Perform frequent, logical commits. Use the standard format: `<type>(<scope>): <description>`.
- **Versioning**: Adhere to Semantic Versioning 2.0.0. Increment versions in `VERSION` or language-specific config as appropriate.
- **Changelog**: Update `CHANGELOG.md` with a curated summary of your changes.
- **Git Notes**: Attach a detailed task summary to the final commit of the task using `git notes`.

### Phase 5: Task Completion
- **Conductor**: Update `plan.md` to mark the task complete `[x]` and record the commit SHA.
- **Phase Checkpoint**: If the task completes a phase, execute the **Phase Completion Protocol**:
    - Perform autonomous verification and present a **Verification Report** (Autonomous vs. Manual).
    - Create a checkpoint commit and record the SHA in `plan.md`.

## 3. Open Source Excellence (The Standard)
Treat EVERY repository as a potential high-quality open-source project.

- **Ownership**: You are SOLELY RESPONSIBLE for setting up and **continuously maintaining** the repository's identity, versioning, and security posture.
- **Maintenance**: You MUST proactively update `README.md`, `CHANGELOG.md`, `LICENSE`, `SECURITY.md`, and all GitHub metadata files (`.github/`) with EVERY relevant change.
- **Required Files**: Every repo MUST include: `README.md`, `LICENSE` (MIT default), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`.
- **GitHub Metadata**: Include `.github/ISSUE_TEMPLATE/` (Bug/Feature) and `.github/PULL_REQUEST_TEMPLATE.md`.
- **README.md**: Must feature an **AI-Friendly TL;DR**, Status Badges (CI, Coverage, Security), a 3-step Quick Start, and comprehensive usage examples.
- **Security Posture**: Maintain `SECURITY.md` and ensure no secrets or vulnerabilities are introduced. Use automated scanners where available.

## 4. Engineering Standards (The Methodology)

### File & System Inspection
- **File Reading**: NEVER use `cat`. Always use the `read_file` tool for surgical or full-file inspection.
- **Verification Policy**: Validation is the only path to finality. ALWAYS attempt to verify state using tools (SSH, `lsblk`, `nix-store`, etc.). Empirically confirm state (kernel params, FS types, etc.) in the target environment.

### Execution Standards
- **Non-Interactive**: Always use non-interactive flags (e.g., `-y`, `--yes`, `--no-pager`) and environment variables (e.g., `CI=true`, `PAGER=cat`).
- **Shell Syntax**: All shell snippets must be valid **Fish** syntax (e.g., `set -x VAR val`, `; and`, `^/dev/null`).

## 5. Ecosystem & Language Standards

### NixOS & System Management
- **Environment**: ALWAYS use **Nix Flakes** and **`direnv`** for seamless activation.
- **Management**: PRIORITIZE **`nh`** (Nix Helper) for EVERY operation it supports (`switch`, `build`, `search`, `clean`).
- **One-off**: Use **`,` (comma)** for ephemeral execution of utilities.

### Python (2026 Gold Standard)
- **Layout**: ALWAYS use the **`src/` layout** to prevent accidental imports and ensure testing against the installed package.
- **Config**: Use **`pyproject.toml`** (PEP 621) with a modern backend like `hatchling`.
- **Tooling**: Use **`uv`** (deps/env), **`ruff`** (lint/format), and **`mypy`** (strict typing).
- **Artifacts**: Include `uv.lock`, `.python-version`, and a `py.typed` marker.
