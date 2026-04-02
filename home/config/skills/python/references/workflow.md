# Python Workflow

## Defaults

- Use `uv` for dependency management and command execution.
- Add `ruff`, `pytest`, and `basedpyright` as dev dependencies with
  `uv add --dev ruff pytest basedpyright`.
- Use the `src/` layout for importable code.
- Keep project metadata in `pyproject.toml`.
- Commit `uv.lock` when dependency state changes.
- Type new and modified code fully unless a concrete blocker is documented.

## Common Commands

```fish
uv add <package>
uv add --dev ruff pytest basedpyright
uv run pytest
uv run ruff check .
uv run ruff format .
uv run basedpyright
```

## When to Use Nix

- Add system libraries, external tools, or non-Python runtime dependencies to
  the flake or dev shell.
- Keep Python package dependencies in `uv` unless they are specifically a
  system-level concern.
