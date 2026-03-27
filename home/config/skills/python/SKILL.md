---
name: python
description: Expert in Python development using uv for environment management and Nix flakes for system-level dependencies. Handles unit and integration testing, formatting with black, import sorting with isort, and linting with pylance.
category: development
risk: low
source: community
date_added: "2026-02-20"
---

# Python Expert Skill

This skill extends the AGENT CLI with specialized workflows for modern Python development, emphasizing reproducibility, strict environment management, and comprehensive testing.

## Core Directives

### 1. Environment Management (uv)
- **Always use `uv`**: Use `uv` for all Python project management (initialization, dependency management, and execution).
- **Project Init**: Use `uv init` for new projects.
- **Dependency Management**:
    - Add dependencies with `uv add <package>`.
    - Use `uv add --dev <package>` for development dependencies.
- **Execution**: Always run Python scripts or tools via `uv run <command>`.
- **Reproducibility**: Ensure `pyproject.toml` and `uv.lock` are maintained and committed.

### 2. System Dependencies (Nix Flakes)
- **Nix for Native Deps**: Use Nix Flakes (`flake.nix`) to manage system-level dependencies (e.g., C libraries, non-Python binaries) that cannot be handled by `uv`.
- **Interpreter**: If a specific Python version is required, specify it in the `flake.nix` devShell.
- **Integration**: Use `direnv` with `use flake` to automatically load the Nix environment.

### 3. Engineering Standards (Linting & Formatting)
- **Formatting**: Use **`black`** for all code formatting (`uv run black .`).
- **Import Sorting**: Use **`isort`** for managing imports (`uv run isort .`).
- **Linting**: Use **`pylance`** (or `pyright` in CLI environments) for static type checking and linting (`uv run pyright`).
- **Automation**: Prioritize running these tools before any commit or pull request.

### 4. Testing Strategy
Maintain a dual testing approach to ensure both logic correctness and system integration.
- **Unit Tests**:
    - Focus on individual functions and classes in isolation.
    - Use **`pytest`** as the primary test runner.
    - Place tests in `tests/unit/`.
- **Integration Tests**:
    - Focus on the interaction between components and external systems (APIs, Databases).
    - Use **`pytest`** with appropriate markers or separate directories.
    - Place tests in `tests/integration/`.
- **Validation**: A task is only complete if both unit and integration tests pass (`uv run pytest`).

### 5. Idiomatic Project Structure
- Use the **`src/` layout** for library code.
- Maintain a clear separation between source code, tests, and configuration.

## Command Reference Matrix

| Action | Command | Tool |
| :--- | :--- | :--- |
| **Init Project** | `uv init` | uv |
| **Add Package** | `uv add <pkg>` | uv |
| **Run Script** | `uv run <file>.py` | uv |
| **Format** | `uv run black .` | black |
| **Sort Imports** | `uv run isort .` | isort |
| **Type Check** | `uv run pyright` | pyright |
| **Run All Tests** | `uv run pytest` | pytest |
| **Run Unit Tests** | `uv run pytest tests/unit` | pytest |
| **Run Int. Tests**| `uv run pytest tests/integration` | pytest |

## Interaction Protocol
1. **Analyze Requirements**: Determine if new dependencies are Python-based (use `uv`) or system-level (use Nix).
2. **Setup First**: Ensure the environment is correctly initialized with `uv` and `flake.nix` before writing code.
3. **Verify Always**: Run formatting, linting, and *both* levels of testing before finalizing any implementation.
