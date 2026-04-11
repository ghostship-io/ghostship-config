## Why

The repo still models Hermes on `chill-penguin` as a three-profile workstation with profile-scoped seeds, Discord/webhook/browser inputs, and profile-facing runtime state, while upstream `ghostship-hermes` now supports one managed agent rooted at `/home/hermes/.hermes`. We need to realign the host module, specs, and docs to the upstream single-agent contract now so future Hermes changes build on the supported runtime model instead of a local forked topology.

## What Changes

- **BREAKING** Remove the repo-owned Hermes profile fleet (`assistant`, `operations`, `supervisor`) from the supported `chill-penguin` runtime contract and replace it with one managed agent rooted at `/home/hermes/.hermes`.
- **BREAKING** Treat the cutover as a destructive reset: stop Hermes and remove `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before deploying the updated image so the new single-agent layout boots from clean persistent state.
- **BREAKING** Replace profile-scoped Discord, webhook, and browser source inputs with the upstream generic single-agent env contract, map the current `supervisor` bot/auth identity into that generic contract, combine the current assistant, operations, and supervisor channels into the generic free-response channel list, preserve the upstream root `.env` defaults and exclusions, rename the current supervisor webhook secret into the generic secret contract while keeping the webhook on the first managed port, and do not set a repo-managed `BROWSER_CDP_URL` default.
- Replace profile-local Hermes seed paths with the upstream root seed layout under `/home/hermes/seeds/`, keep `skill-creator` seeded into the single-agent runtime, normalize copied seed permissions so the runtime-owned skill tree stays writable after bootstrap, and replace the old profile-local persona files with one root `SOUL.md` seed for the unified Crush Crawfish single-agent persona.
- Collapse Hermes routing, runtime-env, and documentation contracts so README, CHANGELOG, AGENTS, and OpenSpec all describe one managed agent, one managed `.env`, one managed skill tree, and one managed `SOUL.md`.
- Keep CloakBrowser support focused on the dedicated `Changedetection` profile instead of also feeding Hermes browser defaults from the managed profile inventory.

## Capabilities

### New Capabilities
- `hermes-single-agent-runtime`: defines the single-agent cutover, including the authoritative `/home/hermes/.hermes` runtime surface, the destructive persistent-state reset before deployment, and the no-default-browser-CDP contract.

### Modified Capabilities
- `hermes-native-layout`: change the persisted mount and verification contract to match the upstream single-agent home/workspace/nix layout on `chill-penguin`.
- `hermes-utility-runtime-env`: replace profile-scoped runtime-env projection with the generic single-agent env contract and remove repo-managed browser-default emission.
- `hermes-profile-skill-seeds`: replace profile-local skill seed behavior with root-only `skill-creator` seeding under `/home/hermes/seeds/skills/`.
- `hermes-profile-souls`: replace profile-local `SOUL.md` seed behavior with one root single-agent `SOUL.md` seed path.
- `hermes-discord-routing`: replace the three-channel Hermes routing policy with a single-agent Discord routing contract.
- `changedetection-service`: remove Hermes browser-default reuse from the managed CloakBrowser profile inventory while preserving the dedicated `Changedetection` profile contract.

## Impact

- Affected code: `modules/self-hosted/hermes.nix`, `modules/self-hosted/cloakbrowser.nix`, Hermes seed assets under `modules/self-hosted/hermes-seeds/`, and the Hermes-related repo docs/specs.
- Affected systems: the `chill-penguin` self-hosted server host, its Podman-managed Hermes container, CloakBrowser integration, and the host deployment workflow because the cutover now includes destructive Hermes state cleanup.
- Manual cleanup/deployment impact: operators must remove the persisted Hermes home, workspace, and `/nix` trees before first deployment of the updated contract and then verify reseeding under the new single-agent layout.
