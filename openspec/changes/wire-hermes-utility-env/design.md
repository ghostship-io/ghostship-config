## Context

The current `chill-penguin` Hermes module already mounts the native
`ghostship-hermes` image layout, passes through a subset of service URLs, and
loads a limited set of service secret bundles into the container. The upstream
image bootstrap already owns the managed profile `.env` files and rewrites them
atomically for `assistant`, `operations`, and `supervisor`, but it currently
projects `BROWSER_CDP_URL` as a shared env key instead of as a per-profile
default.

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

### 1. Selective cross-bundle imports remain the secret strategy

The Hermes container will continue to load existing service-local bundles and
consume the utility-facing variable names they already expose, instead of
copying those secrets into a new Hermes-owned projection file.

Why:

- it avoids creating a second source of truth for service credentials
- it keeps service-local ownership intact
- it matches the current repo pattern where Hermes already imports a subset of
  service bundles directly

Alternatives considered:

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
`SUPERVISOR_BROWSER_CDP_URL`. Upstream managed bootstrap must then write the
matching `BROWSER_CDP_URL` line into each profile's
`~/.hermes/profiles/<profile>/.env`.

Why:

- Hermes expects one persistent default CDP target per profile
- the existing upstream bootstrap already owns rewriting those profile `.env`
  files atomically
- using profile-specific source vars avoids stamping one shared CDP target into
  all profiles

Alternatives considered:

- Keep one shared `BROWSER_CDP_URL`: rejected because it cannot represent
  different profile defaults.
- Post-process the profile `.env` files only from this repo after container
  boot: possible as a workaround, but rejected as the primary design because
  the upstream image explicitly owns the managed profile `.env` contract.

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

- [Risk] The upstream image bootstrap currently treats `BROWSER_CDP_URL` as a
  shared projected env key. → Mitigation: implement the per-profile projection
  in upstream `ghostship-hermes` and consume that updated image contract here.
- [Risk] A CloakBrowser profile may exist but not expose a usable CDP endpoint
  until launched. → Mitigation: document that this change provides the default
  profile-target URL, not guaranteed always-on browser sessions for those three
  profiles.
- [Risk] Selective cross-bundle imports can obscure which utility env comes
  from which service bundle. → Mitigation: document the mapping explicitly in
  the repo and keep Hermes imports limited to only the required bundles.
- [Risk] Some bundled utilities may still rely on optional auth modes that are
  not enabled in this stack. → Mitigation: validate the intended no-auth
  assumptions for qBittorrent and NZBGet and document any residual unsupported
  modes.

## Migration Plan

1. Update the local Hermes module to expose the missing utility-facing URLs and
   selected service-local bundles needed by the shipped utilities.
2. Add the local source env names for profile-specific CloakBrowser defaults.
3. Update upstream `ghostship-hermes` bootstrap so it maps profile-specific
   source env into `BROWSER_CDP_URL` within each managed profile `.env`.
4. Rebuild or roll forward the consumed Hermes image, then activate the local
   NixOS config on `chill-penguin`.
5. Verify the managed profile `.env` files contain the expected utility env and
   per-profile `BROWSER_CDP_URL` values.
6. Roll back by restoring the previous Hermes module wiring and previous image
   reference if the new env projection breaks managed bootstrap or gateway
   startup.

## Open Questions

- Whether `PRICEBUDDY_API_TOKEN` should be projected directly as
  `PRICEBUDDY_TOKEN` inside Hermes, or whether the local module should rename
  it during env wiring.
- Whether any additional bundled utilities require service-local auth variables
  that are not yet represented in existing repo-managed secret bundles.
