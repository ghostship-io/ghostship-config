## Context

Hermes on `chill-penguin` already follows the image's native home layout by
persisting `/srv/apps/hermes/home` at `/home/hermes/.hermes`. That keeps
application state in the location the image expects, but it does not give
operators a separate long-lived workspace path for user-managed files. The user
wants that workspace to stay under `/srv/apps` on the host while appearing
directly at `/home/hermes/workspace` inside the container.

This change is small in scope but it affects the durable filesystem contract of
the live Hermes container, so the mount point and verification path should be
specified before implementation.

## Goals / Non-Goals

**Goals:**
- Add a persistent Hermes workspace on the host at `/srv/apps/hermes/workspace`.
- Bind that workspace directly into the container at `/home/hermes/workspace`.
- Keep Hermes' existing native home mount at `/home/hermes/.hermes` unchanged.
- Declare the host workspace path through NixOS tmpfiles so rebuilds recreate
  it consistently.
- Document the split between Hermes home state and Hermes workspace state.

**Non-Goals:**
- Change the Hermes image tag, registry, or release channel.
- Move the workspace under `/home/hermes/.hermes/workspace`.
- Add symlink indirection for the workspace path inside the container.
- Change Hermes secrets, service URLs, or other runtime environment wiring.

## Decisions

### Decision: Use a separate host path under `/srv/apps/hermes/workspace`

The workspace should live beside the existing Hermes home directory rather than
inside it. That keeps user-managed workspace files distinct from the image's
native `HERMES_HOME` state and makes host-side inspection or backup simpler.

Alternatives considered:
- Store the workspace under `/srv/apps/hermes/home/workspace`. Rejected because
  it mixes operator workspace data into the native application-state tree.
- Use a non-`/srv/apps` host path. Rejected because the repo already treats
  `/srv/apps` as the durable self-hosted data root.

### Decision: Bind directly to `/home/hermes/workspace`

The container should receive a direct bind mount at the exact path the user
wants to use. No symlink or intermediate mount point is needed.

Alternatives considered:
- Mount into `/home/hermes/.hermes/workspace`. Rejected because the user
  explicitly does not want the workspace under the native Hermes home tree.
- Mount elsewhere and symlink `/home/hermes/workspace`. Rejected because it
  adds indirection without any real benefit for this layout.

### Decision: Extend tmpfiles rather than ad hoc startup scripts

The workspace directory should be declared through `systemd.tmpfiles.rules`
alongside `/srv/apps/hermes` and `/srv/apps/hermes/home`. That matches the
repo's declarative host-data pattern and avoids introducing imperative setup
logic into `preStart`.

Alternatives considered:
- Create the directory only from `preStart`. Rejected because tmpfiles are the
  cleaner declarative mechanism for durable host directories in this repo.

## Risks / Trade-offs

- [A direct `/home/hermes/workspace` mount could conflict with a future image-owned path]
  → Mitigation: keep the mount explicit in the Hermes layout contract and verify
  the live container path after activation.
- [Operators may confuse Hermes home state with workspace state]
  → Mitigation: document the two host paths clearly in README and AGENTS.
- [A missing host directory could prevent reliable persistence]
  → Mitigation: create `/srv/apps/hermes/workspace` declaratively through
  tmpfiles before the container starts.

## Migration Plan

1. Update `modules/self-hosted/hermes.nix` to define a `hermes-workspace`
   host path and add `/srv/apps/hermes/workspace:/home/hermes/workspace:rw` to
   the Hermes container volumes.
2. Extend Hermes tmpfiles so `/srv/apps/hermes/workspace` is created with the
   same ownership model as the rest of the Hermes host data.
3. Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the new
   workspace path and the distinction from Hermes home state.
4. Evaluate the `chill-penguin` config and deploy it to the host.
5. Verify the live Hermes container exposes `/home/hermes/workspace` and that
   it is backed by `/srv/apps/hermes/workspace` on the host.

Rollback:
- Remove the workspace bind mount and tmpfiles entry, rebuild the host, and
  switch back to a generation without the workspace contract.

## Open Questions

- None at proposal time. The mount target, host path, and persistence model are
  all explicitly chosen.
