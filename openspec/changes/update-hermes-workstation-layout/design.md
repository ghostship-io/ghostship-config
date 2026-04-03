## Context

Hermes on `chill-penguin` currently mounts `/srv/apps/hermes/home` at
`/home/hermes/.hermes` and `/srv/apps/hermes/workspace` at
`/home/hermes/workspace`. The repo's OpenSpec, README, CHANGELOG, and AGENTS
files all describe that older layout and explicitly say `/nix` is not part of
the normal Hermes runtime contract.

The latest `ghostship-hermes` repo has moved to a workstation-style image
layout with `HERMES_HOME=/opt/data`, `/workspace` as the canonical persisted
work-products mount, and a compatibility symlink from `/home/hermes/workspace`
to `/workspace` owned by the image runtime. The NixOS repo needs to align its
container definition and documentation to that new contract while keeping the
existing host data directories in place under `/srv/apps/hermes`.

## Goals / Non-Goals

**Goals:**
- Align the Hermes NixOS module with the new image contract at `/opt/data` and
  `/workspace`.
- Keep the existing host paths `/srv/apps/hermes/home` and
  `/srv/apps/hermes/workspace` unchanged.
- Restore persistent `/nix` state for Hermes through a named Podman volume.
- Replace stale repo docs and spec text that still describe
  `/home/hermes/.hermes`, `/home/hermes/workspace`, and `/nix` as unnecessary.
- Define a clear activation and verification path for the `chill-penguin`
  server host.

**Non-Goals:**
- Rename or migrate the host data directories under `/srv/apps/hermes`.
- Redesign Hermes environment variables, secrets wiring, or service URLs.
- Rework unrelated self-hosted modules.
- Add repo-side shims for `/home/hermes/workspace`; compatibility symlinks are
  the image's responsibility.

## Decisions

### Decision: Keep the existing host paths and only change the container targets

The repo will continue to persist Hermes data at `/srv/apps/hermes/home` and
workspace data at `/srv/apps/hermes/workspace`, but those host paths will now
mount to `/opt/data` and `/workspace` inside the container.

Alternatives considered:
- Rename the host directories to `/srv/apps/hermes/data` and
  `/srv/apps/hermes/workspace`. Rejected because it adds a host-side data
  migration with no runtime benefit.
- Stage a copy into new host paths and leave the old paths behind. Rejected
  because it increases cutover complexity and rollback surface.

### Decision: Treat `/workspace` as the canonical in-container workspace contract

The repo will mount the host workspace directly at `/workspace`. If the image
chooses to keep `/home/hermes/workspace` as a compatibility symlink, that is an
image-level detail and not part of the host module contract.

Alternatives considered:
- Keep mounting `/home/hermes/workspace` and rely on the image to reconcile it.
  Rejected because it preserves a stale contract and obscures the new canonical
  path.
- Mount both `/workspace` and `/home/hermes/workspace`. Rejected because it is
  redundant and risks conflicting mount behavior with the image's own symlink
  logic.

### Decision: Persist `/nix` through a named Podman volume

Hermes will mount a named volume such as `hermes-nix:/nix:rw` so user-installed
Nix software and build outputs survive container replacement. The rollout
assumes a compatible Hermes image is published before the host module switches
to this contract.

Alternatives considered:
- Leave `/nix` ephemeral. Rejected because the new workstation contract expects
  persistent Nix-managed tooling and outputs.
- Bind-mount the host `/nix` into the container. Rejected because it couples
  the container runtime directly to the host store and departs from the prior
  self-contained Hermes pattern.

### Decision: Replace stale layout-spec text instead of layering exceptions on top

The OpenSpec delta should retire the old `.hermes` and `/home/hermes/workspace`
requirements, add the new `/opt/data`, `/workspace`, and `/nix` contract, and
update post-activation verification so operators validate the new layout
directly.

Alternatives considered:
- Keep the old spec text and explain the new behavior only in implementation
  docs. Rejected because the current spec would remain misleading.
- Preserve `/home/hermes/workspace` as the formal requirement because the image
  may expose a symlink. Rejected because the user explicitly wants `/workspace`
  to be the contractual path.

## Risks / Trade-offs

- [The published `ghcr.io/ghostship-io/ghostship-hermes:latest` image may lag the repo contract]
  -> Mitigation: deploy this change only after a compatible image is published
  or pin the rollout to the first compatible tag.
- [The first `/nix` volume initialization may be slower or larger than current startup]
  -> Mitigation: document the initial volume creation expectation and verify the
  live container against the new image before treating slow first start as a
  regression.
- [Operators may keep relying on `/home/hermes/workspace` out of habit]
  -> Mitigation: document `/workspace` as canonical everywhere in this repo and
  treat any `/home/hermes/workspace` path as image-owned compatibility only.
- [Spec drift around legacy Honcho migration or old layout wording may remain]
  -> Mitigation: update the Hermes layout capability in the same change instead
  of only patching the module.

## Migration Plan

1. Publish a Hermes image whose runtime contract matches `/opt/data`,
   `/workspace`, and persistent `/nix`.
2. Update `modules/self-hosted/hermes.nix` so the existing host directories
   mount to `/opt/data` and `/workspace`, and add the named `/nix` volume.
3. Update `openspec/specs/hermes-native-layout/spec.md`, `README.md`,
   `CHANGELOG.md`, and `AGENTS.md` to reflect the new contract.
4. Rebuild `chill-penguin` with `nixos-rebuild build --flake .#chill-penguin`
   and switch with `./result/bin/switch-to-configuration switch`.
5. Verify the live Hermes container mounts `/opt/data`, `/workspace`, and the
   named `/nix` volume as expected and that existing host data remains intact.

Rollback:
- Restore the previous Hermes module definition and docs, rebuild the host, and
  switch back to the prior generation.
- If necessary, remove the new Hermes `/nix` named volume before restarting
  under the older contract.

## Open Questions

- Whether the first rollout should keep `image = "ghcr.io/ghostship-io/ghostship-hermes:latest"`
  or pin to the first published tag that carries the workstation layout.
- Whether the `/nix` volume string should explicitly include Podman `copy`
  semantics for readability or rely on the backend default.
