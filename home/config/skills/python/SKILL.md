---
name: python
description: Use for Python project structure, uv-based workflows, and this repo's Python defaults around ruff, mypy, and pytest.
---

# python

Use this skill for Python packaging, scripts, tooling, and test workflows.

## Core workflow

- Use `uv` for dependency management and command execution.
- Follow the repo defaults from `home/config/AGENTS.md`: `src/` layout,
  `pyproject.toml`, `uv.lock`, `ruff`, and `mypy`.
- Keep system dependencies in Nix when Python packages alone are not enough.
- Verify formatting, linting, typing, and tests before claiming completion.

## Read when needed

- [Python workflow and checks](references/workflow.md)
