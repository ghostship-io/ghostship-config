# Shared agent preferences

- Be concise. State material assumptions and blockers plainly.
- Scope changes to the request; preserve unrelated user work.
- Inspect the current environment instead of assuming NixOS, WSL, or a username.
- Keep project dependencies in the repo's Nix dev shell; run commands with
  `nix develop -c`. Use the existing container daemon and agent launchers.
- For Python, prefer `uv`, `ruff`, `pytest`, and `basedpyright` when the repo
  has no established alternatives.
- Use non-interactive commands. Keep credentials out of output and commits.
- Verify observable behavior with the smallest relevant checks.
- Update affected documentation, then commit verified work before handoff.
- For agent-facing documents, use `writing-for-agents`: keep common rules
  inline and put task-specific detail behind explicit references.
