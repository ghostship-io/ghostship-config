## Why

Ghostship does not currently provide a repo-managed wiki or documentation service for operator notes and agent-consumable reference material. Adding BookStack now gives the stack a durable self-hosted knowledge base that can be deployed with the rest of the service inventory and surfaced where operators already look for services.

## What Changes

- Add a declarative BookStack service to the self-hosted Podman stack for server hosts, including persistent application state and the required database backing service.
- Add the repo-managed secret wiring and runtime configuration needed to start BookStack with the agreed env surface: `BOOKSTACK_APP_KEY`, `BOOKSTACK_APP_URL`, `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`.
- Preserve manual operator-owned setup for initial BookStack application bootstrap and API key creation rather than trying to fully automate those steps in this repo.
- Surface BookStack in Homepage under the existing `Services` group.
- Update repo documentation and rollout notes for the new service, including any external hostname or ingress follow-up needed after host activation.

## Capabilities

### New Capabilities
- `bookstack-service`: Deploy and surface BookStack as a repo-managed self-hosted service, including its backing database, agreed env surface, manual bootstrap expectations, and Homepage `Services` placement.

### Modified Capabilities
- None.

## Impact

- Affected code: `modules/self-hosted/default.nix`, new `modules/self-hosted/bookstack*.nix` modules, `modules/self-hosted/homepage.nix`, `modules/self-hosted/secrets.nix`, and any supporting host docs.
- Affected systems: server-host self-hosted stack on `chill-penguin`; no develop-host, Home Manager, or Hermes utility-env behavior changes in this change.
- Operational impact: requires host rebuild and service activation, followed by manual BookStack application bootstrap and API key setup; public hostname or Cloudflare tunnel routing may require manual follow-up if that ingress remains managed outside this repo.
