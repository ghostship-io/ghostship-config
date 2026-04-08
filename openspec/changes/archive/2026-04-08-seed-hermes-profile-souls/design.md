## Context

Hermes uses a persistent home tree under `/home/hermes` and supports
profile-specific seed inputs under `/home/hermes/seeds/profiles/<profile>/`.
The repo already tracks the broader Hermes runtime contract, including profile
gateways and copy-once seeding semantics, but it does not currently provide
repo-managed persona files for the three profile gateways. The user has now
defined the exact `SOUL.md` content for:

- `assistant`: Toxic Seahorse
- `operations`: Volt Catfish
- `supervisor`: Crush Crawfish

This change is limited to the Hermes agent runtime. It does not change the
shared develop-host skill model, agent launcher behavior, or the broader
Hermes container contract beyond adding managed persona seed inputs.

## Goals / Non-Goals

**Goals:**
- Keep the three Hermes profile persona definitions in the repo as durable,
  reviewable source text.
- Ensure Hermes seed paths for `assistant`, `operations`, and `supervisor`
  each receive a managed `SOUL.md` file when one is missing.
- Preserve copy-once behavior by refusing to overwrite an existing seeded or
  runtime-owned `SOUL.md`.
- Keep the runtime preparation path declarative and host-driven instead of
  relying on manual file placement.
- Document where operators can find or override the seeded profile persona
  files.

**Non-Goals:**
- Changing the profile names, gateway topology, or Discord wiring.
- Introducing automatic updates to existing `SOUL.md` files after first seed.
- Moving persona instructions into shared develop-host `AGENTS.md` or skills.
- Extending this change to other Hermes runtime assets beyond the three
  profile `SOUL.md` files.

## Decisions

### Decision: Store the persona text as repo-managed source files

The Toxic Seahorse, Volt Catfish, and Crush Crawfish persona definitions will
live in tracked repo files rather than being embedded inline in a shell script.

Why:
- The content is large enough that inline shell heredocs would be noisy and
  hard to review.
- Tracked files produce cleaner diffs when persona text changes later.
- This keeps the Nix module focused on runtime preparation while the persona
  content remains plain data.

Alternatives considered:
- Embed the full text directly in `modules/self-hosted/hermes.nix`. Rejected
  because it makes the module harder to read and review.
- Require operators to create the files manually on the host. Rejected because
  the repo should own the supported runtime seed contract.

### Decision: Seed the files from host preparation before Hermes starts

The Hermes host preparation path will create the per-profile seed directories
and install the repo-managed `SOUL.md` files before the container starts.

Why:
- It aligns with the existing repo responsibility for preparing Hermes runtime
  paths under `/srv/apps/hermes/home`.
- It keeps the seed content present before the containerized Hermes services
  read or copy it.
- It avoids adding another in-container bootstrap path solely for static text
  files.

Alternatives considered:
- Copy the files during `postStart` with `podman exec`. Rejected because the
  container may already have started its own bootstrap flow.
- Let a separate maintenance job manage the files. Rejected because this is
  core runtime scaffolding, not periodic maintenance.

### Decision: Treat existing profile `SOUL.md` files as operator-owned state

If `/home/hermes/seeds/profiles/<profile>/SOUL.md` already exists, runtime
preparation will leave it untouched.

Why:
- The explicit user requirement is copy-once behavior.
- It matches the existing Hermes seed model for non-destructive initialization.
- It prevents rebuilds from clobbering live experiments or profile-specific
  edits.

Alternatives considered:
- Always rewrite the files from the repo. Rejected because it breaks the
  requested runtime contract.
- Rewrite only when the repo version changes. Rejected because it still
  introduces hidden state replacement instead of explicit operator control.

## Risks / Trade-offs

- [Repo-managed persona text can drift from a user's preferred live variant]
  -> Mitigation: preserve existing files and document that updates require
  explicit file removal or manual replacement.
- [Adding another Hermes-managed seed asset could be confused with shared
  skills]
  -> Mitigation: document the `SOUL.md` seed paths separately from the shared
  `.agents/skills` model.
- [Future profile additions would require code changes]
  -> Mitigation: keep the profile-to-file mapping explicit and easy to extend
  in the Hermes module.

## Migration Plan

1. Add the three repo-managed persona source files.
2. Update the Hermes runtime preparation path to create
   `/home/hermes/seeds/profiles/{assistant,operations,supervisor}` and seed
   `SOUL.md` only when missing.
3. Update repo documentation and the changelog to describe the managed persona
   seed behavior.
4. Build the target host config with:
   ```fish
   nixos-rebuild build --flake .#chill-penguin -L
   ```
5. Activate with:
   ```fish
   ./result/bin/switch-to-configuration switch
   ```
6. Verify that each profile seed path contains the expected `SOUL.md` file on
   a fresh deployment and that an existing file is preserved on subsequent
   starts.

Rollback:
- Revert the repo change, rebuild, and switch back to the previous generation.
- Any already-seeded `SOUL.md` files on disk remain as operator-owned state
  unless explicitly removed.

## Open Questions

- Whether the managed persona text should live under a new
  `modules/self-hosted/hermes/` asset directory or another repo path used for
  Hermes-owned static data.
