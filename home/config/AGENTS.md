# Agent Preferences

- Be concise.
- Scope changes tightly to the request.
- Prefer repo-local fixes over global/system changes.
- Record only short durable repo-specific lessons in the project `AGENTS.md` after repeated failures.

## Think Before Coding

- State assumptions when they affect implementation.
- Present material ambiguities instead of silently choosing.
- Prefer the simpler approach.
- Ask only when uncertainty would materially change the solution.

## Simplicity First

- No features beyond what was asked.
- No single-use abstractions.
- No unrequested flexibility.
- No unrelated refactors.
- Every changed line should trace to the request.

## Surgical Changes

- Touch only what is necessary.
- Match existing style.
- Clean up only dead code created by your changes.
- Mention unrelated issues instead of fixing them.

## Goal-Driven Execution

For multi-step tasks, state a brief plan:

```text
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Verify with the smallest relevant check.

## Development Environment

- Inspect the current environment instead of assuming NixOS, WSL2, a username,
  or a home directory. Projects also run in the T3 Code Linux container.
- In containers, use the existing Nix daemon and agent launchers. Keep project
  dependencies in the dev shell; build and activate host systems on the target
  NixOS host through direct root SSH.

### Nix

- Prefer repo-local Nix flakes for development tooling and system dependencies.
- If needed, create a minimal repo-local `flake.nix`.
- Run project commands through the dev shell:

```sh
nix develop -c <command>
```

- Do not use global installs unless explicitly requested.
- Avoid `apt`, `nix-env`, `pip install --user`, global `npm install -g`, or ad-hoc PATH edits for repo dependencies.
- Make the smallest dev-shell change needed.

### Missing dependencies

When a command, package, binary, compiler, library, formatter, linter, test runner, or language server is missing:

1. Identify what is missing.
2. Add tools/system dependencies to the repo-local Nix dev shell.
3. Re-run the failed command with `nix develop -c`.
4. Do not install globally.

### `.envrc`

- Prefer `.envrc` for activating the Nix dev shell.
- For flakes, prefer:

```sh
use flake
```

- Prefer `.envrc` for project environment variables.
- Add missing environment variables as empty stubs only.
- Never add real secrets.
- Preserve existing `.envrc`, `.envrc.example`, `.env.example`, or `.envrc.local` conventions.

## Python Projects

Prefer:

- `uv` for Python dependency and environment management
- `ruff` for linting and formatting
- `pytest` for tests
- `basepyright` for type checking

Use Nix for Python tools, interpreters, compilers, system libraries, and external tools.

Use `uv`, `pyproject.toml`, and `uv.lock` for normal Python package dependencies unless the repo already manages Python packages through Nix.

Preferred commands:

```sh
nix develop -c uv run pytest
nix develop -c uv run ruff check .
nix develop -c uv run ruff format .
nix develop -c uv run basepyright
```

## Windows and WSL2

- Apply these instructions only when running in WSL with Windows interop.
- Prefer `/mnt/c/...` for Windows files.
- Use `wslpath` to translate paths.
- Use Linux paths for Linux/WSL commands.
- Use Windows paths only for Windows-native tools or user-facing Windows output.
- Do not use raw `C:\...` paths in Linux commands.

Examples:

```sh
wslpath 'C:\Users\the owner\project'
wslpath -w /mnt/c/Users/the owner/project
```

## Finish

- Verify changes whenever possible.
- Run relevant tests, lint, typecheck, build, or formatting checks.
- Update `README.md` and affected docs when behavior, setup, configuration, or workflow changes.
- Keep `CHANGELOG.md` current.
- Always bump the version using the repo’s semantic versioning convention.
- Ensure the version and `CHANGELOG.md` are in sync.
- Commit finished work after verification.

Semantic versioning preference:

- `MAJOR` for breaking API, CLI, config, data, migration, or compatibility changes.
- `MINOR` for backward-compatible features or meaningful user-facing behavior changes.
- `PATCH` for fixes, refactors, docs, tests, tooling, performance improvements, and small internal changes.
- Default to `PATCH` when unsure.

## Execution

- Use only non-interactive commands and flags.
- Do not leave unresolved conflicts.
- Do not leave dirty worktrees unless blocked.
- If blocked, report the exact blocker and safest next step.
