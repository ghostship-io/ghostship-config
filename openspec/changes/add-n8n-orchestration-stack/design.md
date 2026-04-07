## Context

`chill-penguin` currently runs self-hosted applications as individual Podman-managed OCI containers declared under `modules/self-hosted/`. Dashboard visibility is split across two repo-managed surfaces: Homepage service tiles are generated surgically in `modules/self-hosted/homepage.nix`, while Muximux service entries and dropdown placement are generated from `modules/self-hosted/muximux.nix` and can still require one-time host-side cleanup after deployment.

The stack does not currently have a general-purpose workflow orchestrator. The user wants `n8n` added as a heavy orchestration engine, but has explicitly constrained the first rollout to SQLite only rather than a queue-mode topology with separate database and broker services. Hermes also needs API access to `n8n`, while browser access should stay behind the existing Cloudflare-gated public-service pattern used elsewhere in the stack.

## Goals / Non-Goals

**Goals:**
- Add a single self-hosted `n8n` service to `chill-penguin` with persisted state under `/srv/apps/n8n`.
- Keep browser access on `https://n8n.ghostship.io` behind the existing Cloudflare/tunnel workflow.
- Keep internal container-to-container API access available so Hermes can call `n8n` directly over `ghostship_net` with an API key.
- Add `n8n` to Homepage `Services` and add a declarative Muximux entry intended to sit immediately after `Bazarr` in the dropdown.
- Capture the required manual Muximux reorder on `chill-penguin` as part of deployment and verification.

**Non-Goals:**
- Introduce queue mode, workers, Redis/Valkey, or Postgres for `n8n` in this change.
- Disable native `n8n` login or replace it with Cloudflare-only authentication.
- Move Cloudflare tunnel route ownership into the repo if it is currently managed outside the repo.
- Design broader workflow libraries, starter automations, or Hermes-side orchestration logic beyond the connection surface.

## Decisions

### Decision: Start with a single SQLite-backed `n8n` instance
The initial deployment will use the upstream `n8n` container with its application home persisted on the host so SQLite, credentials, and workflow state survive container replacement. This matches the user's explicit `sqlite only` constraint and avoids introducing extra moving parts before the workflow surface itself is proven useful.

Alternatives considered:
- Queue mode with Postgres and Redis/Valkey. Rejected for this change because it conflicts with the requested SQLite-only scope and would add more infrastructure than the user wants right now.
- Ephemeral SQLite inside the container. Rejected because workflow state and credentials would be lost across container recreation.

### Decision: Separate browser access from Hermes API access
Public browser traffic will use `https://n8n.ghostship.io` through the existing Cloudflare access pattern, while Hermes will use the internal container address, e.g. `http://n8n:5678`, plus a dedicated API key. This preserves the existing public-service security posture without forcing machine-to-machine traffic through the public hostname.

Alternatives considered:
- Route Hermes through the public Cloudflare hostname. Rejected because it couples automation to browser-facing access controls and adds unnecessary failure points.
- Disable the `n8n` API surface entirely. Rejected because Hermes needs it.

### Decision: Keep native `n8n` login enabled while enabling API-key access for Hermes
Recent `n8n` releases do not support disabling the login screen. The durable contract is therefore Cloudflare Access in front of the public UI, native `n8n` user management for human login, and a dedicated API key for Hermes automation.

Alternatives considered:
- Attempt to disable `n8n` auth. Rejected because the platform no longer supports it.
- Reuse a human operator API key for Hermes. Rejected because it weakens separation between human and automation access.

### Decision: Treat Muximux ordering as declarative intent plus a rollout cleanup step
The repo will generate the desired `Bazarr -> n8n -> ...` dropdown order in `modules/self-hosted/muximux.nix`, but deployment instructions will explicitly include a one-time manual reorder on `chill-penguin`. This matches the repo's current Muximux behavior, where durable intent belongs in Nix but live ordering may still need direct host cleanup after activation.

Alternatives considered:
- Treat manual host ordering as the only source of truth. Rejected because it would leave the repo unable to express the intended layout.
- Ignore the manual cleanup and rely solely on generated ordering. Rejected because the user has already identified that the live host still needs the post-deploy adjustment.

## Risks / Trade-offs

- [SQLite limits future concurrency] → Accept this for the initial rollout and leave queue mode plus external state as a future migration once `n8n` usage patterns are clearer.
- [Cloudflare route for `n8n.ghostship.io` may not be repo-managed] → Call it out as an explicit deployment dependency and verify the public hostname separately from the Nix activation.
- [Hermes API access could be over-privileged] → Use a dedicated `n8n` API key for Hermes rather than reusing a human operator account key.
- [Muximux live order can drift from declarative intent] → Include a manual reorder step and post-deploy verification against the live `settings.ini.php` on `chill-penguin`.
- [Native `n8n` login adds a second auth layer] → Accept the double-gate for browser users because disabling `n8n` auth is unsupported and the Cloudflare-only model does not apply cleanly to internal API clients.

## Migration Plan

1. Add the new `n8n` self-hosted module, import it into the stack, and seed the required secret references.
2. Wire Homepage and Muximux to advertise the service, with the Muximux entry declared immediately after `Bazarr`.
3. Add Hermes-facing environment for the internal `n8n` URL and API key.
4. Deploy the updated host configuration to `chill-penguin`.
5. Verify the `n8n` container is healthy, its SQLite-backed state path exists, Hermes can reach the internal API, and Homepage shows the new tile.
6. Manually reorder the live Muximux entry on `chill-penguin` so `n8n` sits directly under `Bazarr`, then verify the live portal layout.

Rollback: remove the `n8n` module import and dashboard entries from the repo, redeploy the previous system generation, and leave `/srv/apps/n8n` in place for recovery unless the user explicitly wants state cleanup.

## Open Questions

- Whether the Cloudflare route for `n8n.ghostship.io` already exists or must be added outside the repo during rollout.
- Whether Hermes needs only the general `n8n` API surface or also specific workflow/webhook contracts that should be captured in a later change.
