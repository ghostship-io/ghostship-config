## 1. Add the launcher command

- [ ] 1.1 Add a repo-managed `agent-deck-launch` executable to the shared develop Home Manager tooling so it is available on develop hosts after activation.
- [ ] 1.2 Implement current-directory group detection, missing-group creation, and `agent-deck launch . -g <group>` invocation with an optional positional tool argument that defaults to `codex`.
- [ ] 1.3 Implement `YYYY-MM-DD-N` title generation using `agent-deck ... --json` output filtered with `jq`, without reading internal Agent Deck state files.

## 2. Expose the Gemini compatibility command

- [ ] 2.1 Extend the managed Gemini wrapper packaging so `gemini-cli` is installed as a shell-wide command with the same behavior and defaults as `gemini`.
- [ ] 2.2 Verify the launcher continues to accept both `gemini` and `gemini-cli` as tool names without special shell configuration.

## 3. Update docs and verify the config

- [ ] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document `agent-deck-launch`, the shell-wide `gemini-cli` command, and the required rebuild or switch for activation.
- [ ] 3.2 Run concrete verification for the develop-host config, including `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L`, and confirm the resulting configuration includes the new launcher command and the additional `gemini-cli` wrapper.
