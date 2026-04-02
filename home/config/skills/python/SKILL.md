---
name: python
description: Use for Python project structure, uv-based workflows, and this repo's Python defaults around ruff, basedpyright, pytest, and full type coverage.
---

# python

Use this skill for Python packaging, scripts, tooling, and test workflows.

## Core workflow

- Use `uv` for dependency management and command execution.
- Add `ruff`, `pytest`, and `basedpyright` with
  `uv add --dev ruff pytest basedpyright` for project tooling.
- Use the `src/` layout for importable code.
- Keep project metadata in `pyproject.toml` and commit `uv.lock` when
  dependency state changes.
- Keep system dependencies in Nix when Python packages alone are not enough.
- Use `ruff format .` for auto-formatting and `ruff check .` for linting.
- Use `basedpyright` for type checking and treat complete type coverage as the
  default standard for new and modified code.
- Use `pytest` for the full test run before claiming completion.

## Read when needed

- [Python workflow and checks](references/workflow.md)
