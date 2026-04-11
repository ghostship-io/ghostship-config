## 1. Rebase The Hermes Runtime Contract

- [ ] 1.1 Replace the three-profile assumptions in `modules/self-hosted/hermes.nix` with the upstream single-agent contract rooted at `/home/hermes/.hermes`.
- [ ] 1.2 Remove profile-scoped Discord, webhook, and browser env projection, remap the current supervisor bot/auth scope plus the combined assistant/operations/supervisor free-response channel list into the generic single-agent contract, rename the current supervisor webhook secret in `secrets.dec.yaml`, preserve the upstream root `.env` defaults/exclusions with `WEBHOOK_PORT=8644`, and ensure the generated Hermes wiring does not emit `BROWSER_CDP_URL` or any `BROWSER_*_CDP_URL` defaults.
- [ ] 1.3 Rework the live Hermes deployment and verification guidance to treat the cutover as a destructive reset of `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before first start.

## 2. Collapse Seeds And Browser Dependencies

- [ ] 2.1 Replace `modules/self-hosted/hermes-seeds/profiles/...` with the root single-agent seed layout, keep `skill-creator` seeded under the root `/home/hermes/seeds/skills/` path, and normalize copied runtime skill permissions so the managed destination stays writable.
- [ ] 2.2 Collapse the profile-local `SOUL.md` model to one root `/home/hermes/seeds/SOUL.md` source using the provided Crush Crawfish unified single-agent prompt.
- [ ] 2.3 Update `modules/self-hosted/cloakbrowser.nix` so the managed default profile set keeps only `Changedetection`, and Hermes no longer depends on the CloakBrowser profile inventory for browser defaults.

## 3. Rewrite Specs And Docs

- [ ] 3.1 Update `AGENTS.md` with the durable single-agent Hermes runtime contract, the destructive reset requirement, and the retained root `skill-creator` seed path.
- [ ] 3.2 Update `README.md` and `CHANGELOG.md` so active operator guidance describes one managed agent, one managed `.env`, `/workspace` as the generated terminal cwd, no repo-managed browser default, the managed env exclusions, and the required state reset before deployment.
- [ ] 3.3 Keep the OpenSpec deltas in this change aligned with the implementation, including the new `hermes-single-agent-runtime` capability and the modified Hermes/Changedetection specs.

## 4. Verify And Deploy The Cutover

- [ ] 4.1 Run `nix flake check --no-build` in the change worktree and an evaluation-only check such as `nix eval .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath` to confirm the updated host config still evaluates locally.
- [ ] 4.2 From `ssh chill-penguin-root`, pull the updated repo revision, remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`, then build and switch `chill-penguin` with the preferred remote deploy flow.
- [ ] 4.3 Verify live that Hermes bootstraps only the root managed runtime (`/home/hermes/.hermes`), omits a repo-managed `BROWSER_CDP_URL` default, preserves the expected root `.env` defaults/exclusions, reseeds `/srv/apps/hermes/nix`, and copies `skill-creator` from the root seed path into a writable managed skill tree while Changedetection keeps its dedicated CloakBrowser profile.
