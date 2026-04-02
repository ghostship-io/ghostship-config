## Context

The current Hermes host module on `chill-penguin` still forces a legacy startup
path on top of `ghcr.io/ghostship-io/ghostship-hermes:latest`. The repo overrides the
image entrypoint with `/bin/sh`, injects a custom startup script, bind-mounts a
writable `/nix` volume, bind-mounts `/home/hermes/.honcho` separately, and
execs a hardcoded Nix store path for `ghostship-hermes-runtime`.

The current image no longer expects that. Its image config already declares the
native startup path as:

- entrypoint: `/usr/local/bin/ghostship-hermes-runtime`
- command: `entrypoint`
- `HOME=/home/hermes`
- `HERMES_HOME=/home/hermes/.hermes`

The runtime also contains native layout support for Honcho compatibility:

- durable state under `HERMES_HOME`
- a compatibility link at `$HOME/.honcho`
- shared Honcho storage at `$HERMES_HOME/shared/honcho`

On the live host, the durable Hermes state is already stored at
`/srv/apps/hermes/home`, and the legacy Honcho config currently lives at
`/srv/apps/hermes/home/.honcho/config.json`.

## Goals / Non-Goals

**Goals:**
- Align the NixOS Hermes container definition with the image's native
  entrypoint and state layout.
- Preserve durable Hermes state by continuing to mount
  `/srv/apps/hermes/home` at `/home/hermes/.hermes`.
- Migrate the legacy Honcho config into the image's native shared Honcho
  layout.
- Remove repo-side startup overrides that are no longer needed.

**Non-Goals:**
- Change the Hermes image tag, registry, or release channel.
- Redesign Hermes application behavior beyond startup and state layout.
- Introduce a new secret format or change the existing service URLs.
- Rework unrelated self-hosted container modules.

## Decisions

### Decision: Use the image's native entrypoint and command

The NixOS module should stop overriding `entrypoint` and `cmd`, allowing the
image to launch through its own `/usr/local/bin/ghostship-hermes-runtime
entrypoint` path.

Alternative considered:
- Keep a repo-side shell shim and only update its internals. Rejected because
  it preserves drift from the image contract and keeps the hardcoded runtime
  path problem in place.

### Decision: Keep only the native `HERMES_HOME` bind mount

The durable state mount should remain `/srv/apps/hermes/home:/home/hermes/.hermes:rw`.
That is already the image's native home layout. The separate `.honcho` bind
mount and writable `/nix` volume should be removed.

Alternative considered:
- Keep `.honcho` as a top-level bind mount for compatibility. Rejected because
  the image runtime already manages compatibility through
  `$HERMES_HOME/shared/honcho`, and the extra bind mount fights that behavior.

### Decision: Migrate Honcho config into `$HERMES_HOME/shared/honcho`

The existing file at `/srv/apps/hermes/home/.honcho/config.json` should be
moved or copied into `/srv/apps/hermes/home/shared/honcho/config.json` before
or during activation. After the cutover, the image runtime can recreate
`/home/hermes/.honcho` as its compatibility link.

Alternative considered:
- Rely entirely on runtime auto-migration. Rejected because the current host
  keeps `.honcho` outside the native layout, so an explicit host-side migration
  is safer and easier to verify.

### Decision: Preserve current env and secrets wiring unless proven redundant

The image alignment change should focus on startup and filesystem layout first.
The existing environment variables and environment files can remain unless
subsequent testing shows the image now owns more of that contract too.

Alternative considered:
- Remove all repo-provided Hermes environment wiring in the same change.
  Rejected because it increases blast radius and is not required to fix the
  image override drift.

## Risks / Trade-offs

- [Legacy Honcho state may be lost if migration is incomplete] -> Mitigation:
  migrate `config.json` explicitly into `shared/honcho` and verify the file on
  host before switching.
- [The image may still implicitly rely on `/nix` writability for some path] ->
  Mitigation: verify the native image startup path against a disposable run and
  test the deployed host after removing the `/nix` volume.
- [Removing overrides changes startup behavior in one step] -> Mitigation:
  keep the rest of the service contract stable and validate the host
  post-switch through systemd and container inspection.
- [There may be stale legacy files left under `/srv/apps/hermes/home`] ->
  Mitigation: document expected cleanup and only remove obsolete directories
  after the native layout is confirmed healthy.

## Migration Plan

1. Update `modules/self-hosted/hermes.nix` to remove the custom startup script,
   `entrypoint`, `cmd`, `.honcho` bind mount, and `/nix` volume.
2. Keep the `HERMES_HOME` bind mount at `/home/hermes/.hermes`.
3. Add a one-time migration step that ensures
   `/srv/apps/hermes/home/shared/honcho/config.json` exists with the current
   Honcho config.
4. Rebuild and switch `chill-penguin`.
5. Verify the live container now uses the image's native entrypoint and command
   and that the Honcho config is available through the native layout.
6. Remove or archive obsolete legacy host directories if they are no longer in
   use.

Rollback strategy:
- Restore the prior Hermes module definition with the repo-side startup
  overrides and switch back to the previous host generation.
- If needed, copy the Honcho config back into the legacy path before restart.

## Open Questions

- Whether the Honcho migration should be implemented in `preStart` or another
  declarative host-side step. The migration target is clear; only the exact
  delivery mechanism remains to be finalized during implementation.
