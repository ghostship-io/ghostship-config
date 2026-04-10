## Context

The current `chill-penguin` Hermes module already mounts the native
`ghostship-hermes` image layout, passes through a subset of service URLs, and
loads a limited set of service secret bundles into the container. The upstream
image bootstrap already owns the managed profile `.env` files and rewrites them
atomically for `assistant`, `operations`, and `supervisor`. This repo now needs
a host-managed reconciliation step after that bootstrap so profile-specific
utility env and `BROWSER_CDP_URL` values can be projected without forking the
image itself.

The local stack already contains the service credentials and browser topology
needed for a broader Hermes runtime:

- service-local bundles already hold many utility-facing credentials
- CloakBrowser already seeds `assistant`, `operations`, `supervisor`, and
  `Changedetection` profiles
- `changedetection` already demonstrates the correct pattern for resolving a
  managed CloakBrowser profile id and deriving
  `http://cloakbrowser:8080/api/profiles/<id>/cdp`

The missing piece is a deliberate runtime env contract that tells the Hermes
container which service URLs and secrets to expose, and tells the image
bootstrap how to project per-profile browser defaults into each profile's
`.env`.

## Goals / Non-Goals

**Goals:**

- Make the bundled `ghostship-*` utilities usable from the managed Hermes
  profiles against the existing Ghostship stack.
- Keep secret ownership in the existing service-local bundles and selectively
  import only the vars Hermes actually needs.
- Provide profile-specific default CloakBrowser CDP targets for `assistant`,
  `operations`, and `supervisor`.
- Keep router wiring limited to the current provider env required for the
  upstream image's fallback/router path.
- Preserve the existing managed profile `.env` ownership boundary so bootstrap
  remains the single source of truth for profile-facing runtime env.

**Non-Goals:**

- Copy every service secret into a new Hermes-only projection bundle.
- Introduce the full `GHOSTSHIP_ROUTER_*` ranking and tuning surface.
- Force the `assistant`, `operations`, or `supervisor` CloakBrowser profiles to
  be kept running continuously as part of this change.
- Redesign the upstream Hermes profile bootstrap beyond the env projection
  needed for per-profile CDP defaults.

## Decisions

### 1. Hermes will selectively project needed values instead of loading full service bundles

The Hermes runtime will stop loading whole service-local secret bundles into the
container. Instead, repo-managed host-side wiring will read only the required
values from the existing service-local bundles and generated runtime env files,
then project the Hermes-facing utility vars into the managed profile `.env`
files.

Why:

- it avoids creating a second source of truth for service credentials
- it keeps service-local ownership intact
- it matches the desired ownership model where service-local bundles stay the
  source of truth while Hermes receives only the vars it actually needs

Alternatives considered:

- Continue loading whole service-local bundles directly into Hermes: rejected
  because it exposes unrelated service secrets to Hermes and conflicts with the
  desired selective-wiring model.
- Mirror all utility-facing secrets into `hermes-secrets`: rejected because it
  duplicates credential ownership and adds ongoing drift risk.

### 2. The Hermes runtime contract will expose explicit utility-facing URLs

The local module will set the non-secret service URLs directly in the Hermes
container environment, including missing utility-facing URLs such as
`CHANGEDETECTION_URL`, `CHAPTARR_URL`, `PRICEBUDDY_URL`, `RSS_BRIDGE_URL`, and
`SYNOLOGY_URL=http://192.168.200.106:5000/`.

Why:

- these are local topology values, not secrets
- the bundled utilities consistently use environment variables as their runtime
  interface
- centralizing them in the Hermes container definition keeps the contract easy
  to audit and document

Alternatives considered:

- Encode service discovery inside the utilities or profile seeds: rejected
  because the utilities already use env-driven configuration and the repo
  should keep local topology in env/config.

### 3. qBittorrent and NZBGet stay URL-only unless validation disproves the no-auth assumption

The change will expose `QBITTORRENT_URL` and `NZBGET_URL` but will not add
user/password variables unless live validation shows those services are
actually auth-protected for Hermes.

Why:

- the current operating assumption is that auth is disabled
- adding unused credentials increases runtime noise and secret surface

Alternatives considered:

- Add placeholder or speculative credentials preemptively: rejected because the
  repo should not invent managed secrets it does not currently need.

### 4. Per-profile CloakBrowser defaults will be projected into profile `.env`

The desired Hermes-facing shape is still `BROWSER_CDP_URL` inside each profile
`.env`, but the source container env will become profile-specific, for example
`ASSISTANT_BROWSER_CDP_URL`, `OPERATIONS_BROWSER_CDP_URL`, and
`SUPERVISOR_BROWSER_CDP_URL`. A repo-managed host reconciliation step must then write the matching
`BROWSER_CDP_URL` line into each profile's
`~/.hermes/profiles/<profile>/.env` after the image bootstrap generates the
base files.

Why:

- Hermes expects one persistent default CDP target per profile
- the image bootstrap already creates the profile `.env` files that the repo
  can reconcile on the mounted host path
- host-side reconciliation avoids forking the upstream image while still
  preventing one shared CDP target from being stamped into all profiles

Alternatives considered:

- Keep one shared `BROWSER_CDP_URL`: rejected because it cannot represent
  different profile defaults.
- Fork or patch the upstream image bootstrap directly: rejected for this repo
  change because the mounted host profile `.env` files are already a stable
  reconciliation surface and the local host can own the additional utility
  projection without waiting on a separate image rollout.

### 5. CloakBrowser profile ids should be derived, not hard-coded

The repo will reuse the same pattern already used by `changedetection`: resolve
each managed profile id from the CloakBrowser profile store or manager API, and
construct `http://cloakbrowser:8080/api/profiles/<id>/cdp` from that resolved
id.

Why:

- the managed profile ids are runtime data
- the repo already has a working reference implementation for `Changedetection`
- hard-coding ids would be brittle across resets or migrations

Alternatives considered:

- Guess profile ids from names or persist them statically: rejected because the
  manager already provides a durable lookup path.

### 6. Router scope stays minimal

This change will continue to expose only the current provider/runtime env
needed for the image's router and fallback behavior, notably
`OPENROUTER_API_KEY` and `OPENCODE_GO_API_KEY`, without adding the larger
`GHOSTSHIP_ROUTER_*` ranking/tuning matrix.

Why:

- the current goal is utility/runtime usability, not router policy expansion
- the larger router surface introduces additional policy and validation work

Alternatives considered:

- Wire the full router tuning surface now: rejected because it is broader than
  the runtime usability problem being solved.

## Risks / Trade-offs

- [Risk] The image bootstrap can still rewrite the base profile `.env` files
  before the repo-owned reconciliation runs. → Mitigation: keep the local sync
  idempotent, rerun it after Hermes startup, and watch the CloakBrowser profile
  database plus the PriceBuddy token file for later refreshes.
- [Risk] A CloakBrowser profile may exist but not expose a usable CDP endpoint
  until launched. → Mitigation: document that this change provides the default
  profile-target URL, not guaranteed always-on browser sessions for those three
  profiles.
- [Risk] Selective projection can obscure which utility env comes from which
  service bundle or generated runtime file. → Mitigation: document the mapping
  explicitly in the repo and keep the projection code limited to the required
  vars only.
- [Risk] Some bundled utilities may still rely on optional auth modes that are
  not enabled in this stack. → Mitigation: validate the intended no-auth
  assumptions for qBittorrent and NZBGet and document any residual unsupported
  modes.

## Migration Plan

1. Update the local Hermes module to expose the missing utility-facing URLs and
   selected service-local bundles needed by the shipped utilities.
2. Add the local source env names for profile-specific CloakBrowser defaults.
3. Rebuild or activate the local NixOS config on `chill-penguin` so the host
   owns both the generated `runtime.env` projection and the post-bootstrap
   profile `.env` reconciliation.
4. Verify the managed profile `.env` files contain the expected utility env and
   per-profile `BROWSER_CDP_URL` values.
5. Roll back by restoring the previous Hermes module wiring if the new env
   projection or reconciliation breaks managed bootstrap or gateway startup.

## Open Questions

- Whether `PRICEBUDDY_API_TOKEN` should be projected directly as
  `PRICEBUDDY_TOKEN` inside Hermes, or whether the local module should rename
  it during env wiring.
- Whether any additional bundled utilities require service-local auth variables
  that are not yet represented in existing repo-managed secret bundles.
