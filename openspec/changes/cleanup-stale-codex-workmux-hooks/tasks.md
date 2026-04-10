## 1. Implement stale Codex hook cleanup

- [ ] 1.1 Update the develop-host Home Manager or shared cleanup logic so it detects `~/.codex/hooks.json` and removes only the stale `workmux set-window-status working` and `workmux set-window-status done` Codex hook commands.
- [ ] 1.2 Ensure the cleanup path preserves unrelated valid Codex hook entries and tolerates empty hook groups or an effectively empty hooks file after stale-command removal.
- [ ] 1.3 Confirm the repo-managed convergence path does not recreate the removed `workmux` Codex hook commands on later rebuild or switch runs.

## 2. Update documentation and repo memory

- [ ] 2.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` so they describe the stale Codex hook cleanup behavior, activation expectations, and the need to restart already-running Codex or Agent Deck sessions after the cleaned state lands.
- [ ] 2.2 Verify the active documentation no longer leaves the impression that removed repo-managed tooling can still remain wired into Codex hooks after develop-host convergence.

## 3. Verify the change

- [ ] 3.1 Run concrete evaluation or build checks for the affected develop-host configuration, such as `nix eval -L .#homeConfigurations.nixos@armored-armadillo.config.home.activationPackage.outPath` and any narrower inspection command needed to confirm the stale Codex hook cleanup is present in the generated activation logic.
- [ ] 3.2 Exercise the cleanup against a representative stale `~/.codex/hooks.json` fixture or live-safe host state to verify the stale `workmux` entries are removed while unrelated hooks remain intact.
- [ ] 3.3 Run `openspec status --change cleanup-stale-codex-workmux-hooks` and confirm the change artifacts remain apply-ready after the implementation and verification steps are complete.
