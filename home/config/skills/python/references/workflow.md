# Python Workflow

## Defaults

- Use `uv` for dependency management and command execution.
- Use the `src/` layout for importable code.
- Keep project metadata in `pyproject.toml`.
- Commit `uv.lock` when dependency state changes.

## Common Commands

```fish
uv add <package>
uv add --dev <package>
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy .
```

## When to Use Nix

- Add system libraries, external tools, or non-Python runtime dependencies to
  the flake or dev shell.
- Keep Python package dependencies in `uv` unless they are specifically a
  system-level concern.
