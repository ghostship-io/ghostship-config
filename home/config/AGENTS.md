# Agent Preferences

Use these defaults across repos unless a repo-level `AGENTS.md` overrides them.

## Default stance

- Use the project `AGENTS.md` as the workspace memory.
- Record durable corrections and lessons in the project `AGENTS.md`.
- Keep responses concise. Lead with commands, then short rationale.
- Ask focused questions when requirements are unclear or risky.

## Research and planning

- Research the current state before changing code or config.
- Use the `brainstorming` skill for research when it is available.
- Use `openspec-explore` when researching a repo to understand how it works.
- If the work needs a plan, implement it in a git worktree.
- If `using-git-worktrees` is available, activate it for planned work.

## Completion standard

- Verify your own changes whenever possible.
- Update the README and any affected supporting documentation before finishing.
- Keep the changelog current.
- Bump the project version when the change warrants it.
- Commit finished work after verification.
- Use commit messages in the form `<type>(<scope>): <description>`.

## Execution

- Use only non-interactive commands and flags.
- Write shell examples for the user in Fish syntax.
- Do not use `sudo`.
- When elevation is required, use a root shell or direct root SSH host.

## Skill routing

- Use the most relevant available skill instead of repeating detailed platform
  or language rules here.
- Use the `nix` skill for Nix-platform work when it is available.
- Use the `python` skill for Python code or Python project structure when it is
  available.
