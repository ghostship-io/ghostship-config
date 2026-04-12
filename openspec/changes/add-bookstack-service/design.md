## Context

Ghostship's self-hosted services are declared as flat NixOS modules under `modules/self-hosted/` and run as repo-managed Podman containers on `chill-penguin`. User-facing services commonly include durable state under `/srv/apps/<name>`, repo-managed secret projection via `sops.secrets`, container healthchecks, and Homepage visibility generated in `modules/self-hosted/homepage.nix`.

BookStack adds a new documentation/wiki service that does not currently exist in the stack. The operator has decided that BookStack API tokens and the initial application setup will be managed manually, but Hermes should still receive the final BookStack endpoint and token pair through the existing utility-runtime env projection once those values are present in the service-local secret bundle.

## Goals / Non-Goals

**Goals:**
- Add BookStack as a declarative self-hosted application in the server-host Podman stack.
- Add the backing database, persistent state paths, and secret-driven runtime configuration BookStack needs to start cleanly after activation.
- Keep the service env surface aligned to the agreed names: `BOOKSTACK_APP_KEY`, `BOOKSTACK_APP_URL`, `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`.
- Surface BookStack in Homepage under the existing `Services` group.
- Project `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET` into Hermes through the existing repo-managed utility env sync path.
- Capture deployment and documentation implications for the new service, including the required manual bootstrap and API-token setup.

**Non-Goals:**
- Automate BookStack admin bootstrap, API token provisioning, or other first-run application setup.
- Rework Muximux ordering or portal layout unless a follow-up change explicitly requests it.
- Rework Cloudflare tunnel ownership or guarantee that public ingress is fully repo-managed if that routing still lives elsewhere.

## Decisions

### Add dedicated `bookstack.nix` and `bookstack-db.nix` modules

BookStack should follow the repo's existing self-hosted pattern of one module per service or tightly coupled database dependency instead of being inlined into `homepage.nix` or another utility module. This keeps runtime state, healthchecks, dependencies, and future service-specific adjustments isolated and consistent with modules such as `grimmory.nix` and `grimmory-db.nix`.

Alternatives considered:
- Fold BookStack into a single monolithic module with both app and DB configuration. Rejected because the repo already models app/database pairs as separate modules when the database has its own persistent state and lifecycle.
- Use an unmanaged host-side container. Rejected because the service should survive rebuilds and remain part of the declarative host inventory.

### Use repo-managed env generation from a dedicated BookStack secret bundle

The repo should add a dedicated `bookstack-secrets` bundle in `modules/self-hosted/secrets.nix` and generate the application/database env files during activation or pre-start. The managed env surface should include `BOOKSTACK_APP_KEY`, `BOOKSTACK_APP_URL`, `BOOKSTACK_DB_DATABASE`, `BOOKSTACK_DB_USER`, `BOOKSTACK_DB_PASS`, and `BOOKSTACK_DB_ROOT_PASS`, with `BOOKSTACK_APP_URL` set to the external canonical URL.

Alternatives considered:
- Hard-code bootstrap credentials or generate them only inside the container. Rejected because this would break declarative recovery and make rebuild outcomes depend on mutable in-container setup.
- Reuse an existing shared secret bundle. Rejected because this service has a distinct credential surface and should not widen unrelated secret scopes.

### Reuse the existing Hermes runtime-env projection path for BookStack

Hermes already receives selected service URLs as container env and selected secret-backed values through `/srv/apps/hermes/runtime.env`. BookStack should reuse that path by adding `BOOKSTACK_URL` to the static utility env set and projecting `BOOKSTACK_TOKEN_ID` plus `BOOKSTACK_TOKEN_SECRET` from `bookstack-secrets` alongside the rest of the selected utility auth values.

Alternatives considered:
- Delay Hermes integration to a later change. Rejected because the user wants Hermes wired now.
- Create a second Hermes-only BookStack secret file. Rejected because the existing runtime-env sync path already exists to avoid duplicated secret bundles.

### Leave initial app bootstrap and API-token setup manual

The service module should stop at bringing up BookStack and its database with the required secret/env wiring. Initial application setup and the creation of `BOOKSTACK_TOKEN_ID` plus `BOOKSTACK_TOKEN_SECRET` remain manual operator steps so the repo does not need to encode BookStack-specific first-run automation or opinionated API-token lifecycle management.

Alternatives considered:
- Seed an admin user and API token declaratively. Rejected because the operator explicitly wants to handle those pieces manually.
- Store a pre-created API token in the service bootstrap path. Rejected because the repo does not need to automate that credential lifecycle yet.

### Treat Homepage placement as part of the BookStack capability

The request is specifically that BookStack appear under `Services`, and Homepage already owns that grouping declaratively in `modules/self-hosted/homepage.nix`. The BookStack capability should therefore include Homepage placement directly rather than introducing a separate dashboard-only capability.

Alternatives considered:
- Model Homepage placement as a separate capability. Rejected because the placement is a small, service-specific requirement tied directly to the BookStack rollout.
- Also update Muximux in the same change. Deferred because the user only requested `Services` placement, which maps directly to Homepage in the current repo structure.

### Keep ingress follow-up explicit but outside the core deployment contract

The application runtime should still be configured with the intended external base URL so the deployment shape is correct, but the proposal should not assume Cloudflare tunnel or DNS wiring is fully repo-managed. That work can be validated during apply and either implemented here if the repo already owns it or captured as manual follow-up.

Alternatives considered:
- Make public hostname provisioning a hard requirement of this change. Rejected because the current repo evidence does not show declarative ingress mappings for every app.
- Ignore the external URL entirely. Rejected because BookStack's application config needs a coherent deployment URL even if routing work is separate.

## Risks / Trade-offs

- [BookStack image expectations differ from the repo's usual service patterns] → Mitigation: model the module after the existing app-plus-database services, keep healthchecks explicit, and verify the resulting env/volume contract during implementation.
- [Manual bootstrap is forgotten after activation] → Mitigation: make the manual setup and API token creation steps explicit in docs and apply notes.
- [Hermes starts before BookStack secrets exist] → Mitigation: extend the Hermes secret wait and path-watch lists to include `bookstack-secrets` so runtime env sync stays consistent.
- [Homepage placement succeeds while external access is still missing] → Mitigation: document ingress as a deployment checkpoint and avoid treating the dashboard entry alone as proof of full rollout.

## Migration Plan

1. Add `bookstack-secrets` and new `bookstack` / `bookstack-db` modules to the self-hosted module inventory.
2. Generate the BookStack application and database runtime env files with durable state directories under `/srv/apps`, using the agreed env names.
3. Add the Homepage `Services` entry for BookStack.
4. Extend Hermes runtime env projection to include `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, and `BOOKSTACK_TOKEN_SECRET` from the BookStack secret bundle.
5. Update docs and rollout notes, including the manual BookStack bootstrap and API-token setup steps, then evaluate and build the affected host configuration.
6. Apply the host configuration on `chill-penguin` and verify the containers, persistent state, Homepage entry, Hermes runtime env projection, and any required ingress follow-up.

Rollback:
- Remove the BookStack modules, secret declaration, Homepage entry, and Hermes env projection, then rebuild and switch the host back.
- Retain or manually clean up `/srv/apps/bookstack*` state depending on whether rollback is temporary or permanent.

## Open Questions

- Which public hostname should be canonical for BookStack, if any, and is that ingress already managed outside this repo?
- Which BookStack and MariaDB images/versions fit the stack best during apply, assuming the repo follows its normal Podman patterns?
