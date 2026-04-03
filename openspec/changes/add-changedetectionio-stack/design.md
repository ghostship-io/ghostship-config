## Context

Ghostship's self-hosted stack is declared under `modules/self-hosted/` and
deployed as Podman containers on `chill-penguin`. Dashboard visibility is also
repo-managed: Homepage service tiles are written surgically into
`/srv/apps/homepage/services.yaml`, while Muximux tile ordering is generated
from the activation script in `modules/self-hosted/muximux.nix`.

CloakBrowser is already managed as a long-lived browser-profile service with
repo-owned startup logic that seeds persistent profiles directly in the
manager's SQLite database. `changedetection.io` adds one more cross-service
dependency because browser-backed checks need a stable Playwright CDP endpoint,
not just a generic browser container on the network.

The repo does not currently model `changedetection.io`, and the existing
`muximux-service-placement` spec only covers PriceBuddy/Honcho ordering. This
change therefore needs one new capability plus a delta to the existing Muximux
placement contract.

## Goals / Non-Goals

**Goals:**
- Add a declarative `changedetection.io` service module to the server-host
  stack with durable state on `chill-penguin`.
- Make browser-backed checks target a dedicated persistent CloakBrowser profile
  named for `changedetection.io`.
- Derive a stable `PLAYWRIGHT_DRIVER_URL` from that dedicated profile and keep
  the dependent service startup tied to the CloakBrowser manager.
- Surface the new service in Homepage and place it in Muximux immediately after
  `RSS-Bridge`.
- Capture the service addition and host rollout implications in repo docs.

**Non-Goals:**
- Add repo-managed `changedetection.io` API key export for Hermes.
- Redesign existing Homepage or Muximux groups beyond the requested service
  insertion.
- Rework external ingress or Cloudflare tunnel ownership if the public hostname
  still depends on config outside this repo.

## Decisions

### Add a dedicated `modules/self-hosted/changedetectionio.nix` service module

The new service should follow the existing flat self-hosted inventory pattern
instead of being embedded into `homepage.nix`, `muximux.nix`, or
`cloakbrowser.nix`. The module will define the container, persistent state
directory, healthcheck, and any runtime artifacts required to launch with a
resolved `PLAYWRIGHT_DRIVER_URL`.

Alternatives considered:
- Fold the service into an existing dashboard module. Rejected because the
  service has its own runtime, state, and dependency lifecycle.
- Keep the service as an unmanaged host-side container. Rejected because the
  stack is repo-owned and should survive rebuilds.

### Seed a named CloakBrowser profile in the existing startup bootstrap

The current CloakBrowser startup script already initializes persistent profiles
by talking directly to the manager's database helpers. Extending that path to
ensure a `Changedetection` profile exists is simpler and more durable than
trying to click through the manager UI or depend on a post-start API create.

Alternatives considered:
- Create the profile through the manager REST API after startup. Rejected
  because the DB bootstrap already exists and is less timing-sensitive.
- Reuse the `Direct` or `VPN` profiles. Rejected because the request is for a
  dedicated default profile that can evolve independently.

### Resolve the profile ID at runtime and generate the CDP URL from the name

CloakBrowser profile IDs are UUIDs stored in the manager DB, so the repo should
not hard-code one. A small repo-managed runtime helper can read the persistent
profile store by name, emit a `changedetection.env` file with
`PLAYWRIGHT_DRIVER_URL=http://cloakbrowser:8080/api/profiles/<id>/cdp`, and
keep the service dependency coupled to CloakBrowser readiness.

Alternatives considered:
- Hard-code a profile UUID in Nix. Rejected because it would drift if the DB is
  recreated or the profile is manually replaced.
- Leave `PLAYWRIGHT_DRIVER_URL` unset and require operators to paste a CDP URL
  in the UI. Rejected because it defeats the declarative goal of the change.

### Launch the dedicated profile as part of the managed runtime flow

The service should not rely on operators to manually press "Launch" in
CloakBrowser every time the stack is rebuilt. The managed runtime path should
ensure the named profile is launched before `changedetection.io` depends on its
CDP endpoint, using the manager's local API after the profile exists.

Alternatives considered:
- Assume `changedetection.io` will lazily tolerate a stopped profile. Rejected
  because the browser-backed integration would remain partially broken after
  activation.
- Launch all CloakBrowser profiles by default. Rejected because it expands the
  scope and resource footprint beyond this service's need.

### Treat Homepage visibility as part of the new capability and Muximux order as
an existing-capability modification

Homepage currently has no dedicated placement spec for this service set, while
Muximux already has an archived and active ordering contract. The clean spec
boundary is: new `changedetectionio-service` requirements for service presence
and CloakBrowser integration, plus a modified `muximux-service-placement`
requirement for the specific ordering change after `RSS-Bridge`.

## Risks / Trade-offs

- [CloakBrowser manager API or schema drifts] → Keep the name-to-ID resolution
  based on the persisted profile store already owned by the repo and validate
  the launch path during rollout.
- [Profile launch ordering races `changedetection.io` startup] → Tie the new
  service to explicit `after`/`requires` style systemd hooks and generate the
  runtime env only after the profile exists.
- [Public hostname routing is still managed elsewhere] → Call out the external
  ingress dependency in docs and rollout notes so activation success is not
  mistaken for full public availability.
- [Dashboard specs drift again] → Update the `muximux-service-placement` delta
  in the same change so the new order is archived with the implementation.

## Migration Plan

1. Add the new module and import it into the self-hosted inventory.
2. Extend CloakBrowser bootstrap so the `Changedetection` profile exists by
   default.
3. Generate the runtime env that resolves and launches the dedicated profile,
   then start `changedetection.io` with the resulting CDP URL.
4. Update Homepage and Muximux definitions, then refresh docs and specs.
5. Build and activate on `chill-penguin`, verify the service, profile-backed
   browser integration, and dashboard placement.

Rollback:
- Remove the module import and dashboard entries, then rebuild.
- If needed, leave the extra CloakBrowser profile in place as harmless retained
  state, or remove it manually from the manager after rollback.

## Open Questions

- Whether the public `changedetection.ghostship.io` hostname and tunnel route
  are already covered by infrastructure outside this repo or need a separate
  follow-up.
