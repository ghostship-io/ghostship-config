## Context

`ghcr.io/ghostship-io/ghostship-hermes:latest` no longer uses the April 3, 2026
workstation contract that this repo currently documents and mounts. The active
image contract now expects a persisted `/home/hermes` tree with managed Hermes
state under `/home/hermes/.hermes`, a separate persistent `/workspace`, and a
usable persistent `/nix` for mutable Nix installs and build outputs. The image
also treats the managed Hermes profile gateways as first-class runtime services
and supports runtime skill seeding from `/home/hermes/seeds/...`.

The current repo state is misaligned in several ways:

- `modules/self-hosted/hermes.nix` still mounts `/srv/apps/hermes/home` at
  `/opt/data`.
- The current OpenSpec and README text still describe `/opt/data` and a named
  `/nix` volume as the supported contract.
- The repo currently passes only a subset of the environment required for the
  current profile-gateway-first Hermes runtime.
- The repo does not yet define host-side scaffolding for skill seeding under
  `/home/hermes/seeds/...`.
- A naive empty mount at `/nix` would hide the image's prebuilt `/nix` content
  and break the runtime.

This change affects the `chill-penguin` server host, the Hermes NixOS module,
Hermes secrets wiring, and the active documentation and specs. It does not
change the shared `~/.agents/skills` model used by Codex, Gemini, and OpenCode
outside the Hermes container.

## Goals / Non-Goals

**Goals:**
- Align the self-hosted Hermes module with the current upstream whole-home
  runtime contract by mounting `/srv/apps/hermes/home` at `/home/hermes`.
- Keep `/srv/apps/hermes/workspace` mounted at `/workspace`.
- Persist `/nix` on the host under `/srv/apps/hermes` and seed it from the
  image before the first mounted start so the runtime does not lose the image
  store.
- Treat the Hermes profile gateways as first-class runtime services and ensure
  they receive the required Ghostship service URLs, secrets, Discord config,
  and router credentials.
- Add host-side scaffolding for runtime skill seeding from
  `/home/hermes/seeds/shared/skills` and
  `/home/hermes/seeds/profiles/<profile>/{skills,SOUL.md}`.
- Keep the image reference unpinned and treat `latest` as the supported ongoing
  contract for this integration.
- Update specs, README, CHANGELOG, and AGENTS to document the new contract and
  cutover path.

**Non-Goals:**
- Pinning Hermes to a tagged or digested image reference.
- Changing the shared repo-managed skill inventory under `home/config/skills/`.
- Redesigning the upstream Hermes profile scaffold, router behavior, or Discord
  profile model beyond wiring the repo to the current contract.
- Moving Hermes data out of `/srv/apps/hermes`.
- Introducing a repo-local startup shim in front of the image's native runtime.

## Decisions

### Decision: Persist the whole Hermes home tree at `/home/hermes`

The repo will stop mounting Hermes durable state at `/opt/data` and will mount
`/srv/apps/hermes/home` directly at `/home/hermes`. Hermes-managed state under
`/home/hermes/.hermes`, runtime-owned profile state, router state under
`/home/hermes/.local/state/...`, and seeded runtime inputs under
`/home/hermes/seeds/...` will all live under that persisted tree.

Why:
- It matches the current image contract.
- It keeps managed state, profile state, and seed inputs in one inspectable
  host-backed tree.
- It avoids reintroducing a repo-owned compatibility facade around upstream
  paths.

Alternatives considered:
- Keep `/opt/data` and try to adapt the image around it. Rejected because it
  preserves a stale contract and would turn the repo into an unsupported image
  wrapper again.
- Split only `HERMES_HOME` out of `/home/hermes`. Rejected because the current
  image contract expects the whole home tree to persist and uses it for more
  than `.hermes`.

### Decision: Use a host bind mount for `/nix` instead of a named Podman volume

The repo will replace the named `hermes-nix` volume with a host path such as
`/srv/apps/hermes/nix:/nix`.

Why:
- The host path is durable under normal container churn and does not depend on
  Podman volume lifecycle or pruning behavior.
- It gives the repo a deterministic place to inspect, back up, repair, and
  seed the Hermes Nix state.
- It lets the migration prepare `/nix` explicitly before first mounted start.

Alternatives considered:
- Keep a named Podman volume and rely on volume copy-up. Rejected because the
  copy semantics are implicit and fragile for a critical runtime path, and the
  retention story is weaker than a host bind mount.
- Leave `/nix` ephemeral. Rejected because the current Hermes runtime expects
  mutable Nix installs and build outputs to survive container replacement.

### Decision: Seed the host `/nix` path from the image before the first mounted start

The migration will treat `/srv/apps/hermes/nix` as uninitialized until it
contains a valid seeded Nix tree. The host module should prepare that path from
the current image before the real Hermes container starts with `/nix` mounted.

Why:
- Mounting an empty host path on `/nix` would hide the image's `/nix` store and
  break the runtime immediately.
- A first-class seed step makes the cutover deterministic and inspectable.
- It provides a clean place to document rollback and repair behavior.

Alternatives considered:
- Assume the target path was pre-seeded manually. Rejected because the repo
  should own the supported migration path.
- Seed lazily from inside the mounted container after startup. Rejected because
  the runtime may already be broken once the empty mount hides the image store.

### Decision: Treat profile gateways as the primary Hermes integration surface

The repo will align to the upstream image's profile-gateway-first runtime and
will consider `assistant`, `operations`, and `supervisor` as the primary Hermes
interaction modes.

Why:
- That is the user requirement for this stack.
- It matches the active image contract.
- It clarifies that environment propagation has to reach profile services and
  bootstrap paths, not just the container's top-level process environment.

Alternatives considered:
- Treat the gateways as optional and use Hermes mainly through the dashboard or
  interactive terminals. Rejected because it conflicts with the intended
  operating model.

### Decision: Propagate Ghostship integration envs into bootstrap, router, and profile gateways

The repo will expand Hermes wiring so Ghostship service URLs, service auth
secrets, model-provider credentials, Discord settings, router credentials, and
seed-directory settings are available where the current image actually consumes
them.

Why:
- Container-level env alone is not enough when the real Hermes work runs inside
  NixOS-managed services in the container.
- The profile gateways need the same Ghostship service topology and auth that
  interactive Hermes sessions rely on.
- The bootstrap path needs the model and seed configuration to materialize the
  intended Hermes state.

Alternatives considered:
- Keep all extra env only at the outer container layer. Rejected because the
  profile gateways are the real working surface.
- Hardcode service URLs and credentials into image-managed config files.
  Rejected because secrets must remain external and the local topology belongs
  in deployment env, not the published image.

### Decision: Add host-side scaffolding for runtime skill seeding under `/home/hermes/seeds`

The repo will create and document the persistent host paths that back:

- `/home/hermes/seeds/shared/skills`
- `/home/hermes/seeds/profiles/assistant/skills`
- `/home/hermes/seeds/profiles/assistant/SOUL.md`
- `/home/hermes/seeds/profiles/operations/skills`
- `/home/hermes/seeds/profiles/operations/SOUL.md`
- `/home/hermes/seeds/profiles/supervisor/skills`
- `/home/hermes/seeds/profiles/supervisor/SOUL.md`

The image remains responsible for copy-once seeding semantics into
Hermes-owned state; the repo is responsible for exposing persistent input paths
and documenting how operators populate them.

Why:
- The user plans to generate skills for this runtime.
- The current image contract already supports runtime seeding from those paths.
- The repo needs declarative host scaffolding so this is a supported surface,
  not an undocumented side path.

Alternatives considered:
- Reuse the shared repo-managed `~/.agents/skills` inventory inside Hermes.
  Rejected because Hermes runtime seeding is a separate concern from the shared
  develop-host skill layer.
- Bake the skills into the image. Rejected because the user wants to own and
  evolve them as runtime state.

## Risks / Trade-offs

- [A bad `/nix` seed could leave Hermes unbootable on first cutover]
  -> Mitigation: make the seed step explicit, gated, and verifiable before the
  container starts with the new mount.
- [The unpinned `latest` image contract may change again]
  -> Mitigation: document that the repo intentionally tracks the current image
  contract and keep the spec/docs aligned when upstream changes.
- [Profile gateways may still miss env the image does not currently pass
  through]
  -> Mitigation: audit the actual bootstrap, router, and profile service env
  paths during implementation and extend repo wiring to the exact services that
  need the Ghostship variables.
- [Persisting the full home tree retains more mutable state]
  -> Mitigation: keep the contract documented and provide clear inspection paths
  under `/srv/apps/hermes/home`.
- [Runtime skill seeding could be confused with shared repo-managed skills]
  -> Mitigation: document Hermes seed paths separately from `home/config/skills`
  and preserve the existing shared-skill model unchanged.

## Migration Plan

1. Update the Hermes OpenSpec and docs to describe persisted `/home/hermes`,
   `/workspace`, and host-mounted seeded `/nix`.
2. Update `modules/self-hosted/hermes.nix` to:
   - mount `/srv/apps/hermes/home` at `/home/hermes`
   - mount `/srv/apps/hermes/workspace` at `/workspace`
   - mount a host path such as `/srv/apps/hermes/nix` at `/nix`
   - expose the required Hermes, router, Discord, model, service, and seed
     environment variables
   - declare tmpfiles or equivalent scaffolding for the new persistent paths
3. Add or update secrets wiring for the Hermes runtime credentials and service
   auth secrets that now need to reach the profile gateways and router.
4. Add a host-side Hermes `/nix` seed step that initializes the persistent
   `/srv/apps/hermes/nix` path from the current image before the first mounted
   start.
5. Rebuild `chill-penguin` with:
   `nixos-rebuild build --flake .#chill-penguin`
6. Activate with:
   `./result/bin/switch-to-configuration switch`
7. Verify:
   - `/home/hermes`, `/workspace`, and `/nix` mounts are correct
   - `assistant`, `operations`, and `supervisor` gateways are active
   - router and dashboard are healthy
   - required Ghostship service env is visible in the Hermes-managed runtime
   - runtime seed paths under `/home/hermes/seeds/...` are available

Rollback:
- Restore the previous Hermes module and docs from Git, rebuild the host, and
  switch back to the prior generation.
- If the new `/nix` bind mount must be abandoned, stop Hermes, preserve the
  seeded host path for inspection, and revert to the previous runtime contract.

## Open Questions

- Which exact host path under `/srv/apps/hermes` should back `/nix`
  (`/srv/apps/hermes/nix` is the leading candidate)?
- Which non-secret Ghostship service env vars need to live in the shared
  Hermes `.env` versus only in service `PassEnvironment`?
- Whether any additional browser-provider envs beyond `BROWSER_CDP_URL` should
  be wired in the first pass, or deferred until an operator actually needs
  them.
