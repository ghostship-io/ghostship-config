## Context

This repo currently wires secrets through `sops-nix`, a single encrypted `secrets.yaml`, and module-local references such as `config.sops.secrets."...".path`. Multiple services consume shared secret data by sourcing whole env bundles and selecting the fields they need in ad hoc shell hooks or `environmentFiles` lists. Host onboarding is similarly coupled: `bootstrap.sh` creates a JSON payload that mixes host identity, an age public key, and an embedded `hardware-configuration.nix`, while `sops-register-host` mutates repo state around that payload.

The requested redesign changes both data shape and workflow. Secret storage moves from one monolithic encrypted YAML to logical-unit `.age` files managed through `ragenix`. Recipient policy moves to a centralized model based on SSH host `ed25519` public keys. Shared secret consumption needs a cleaner pattern than repeated raw-file sourcing, so the new design needs a catalog that declares both storage metadata and exported fields, plus a projection layer that builds the minimal env/config surfaces each consumer needs. Host intake also needs to become file-based and temporary so Codex can integrate a new host from concrete repo-local artifacts instead of pasted JSON.

## Goals / Non-Goals

**Goals:**
- Replace `sops-nix` with `ragenix` without preserving the repo-wide `secrets.yaml` monolith.
- Store secrets as logical-unit encrypted files that remain practical to edit, review, and rekey.
- Centralize recipient policy in `secrets/recipients.nix` and secret definitions in `secrets/catalog.nix`.
- Let multiple services consume shared secret fields through declarative projections instead of repeated raw path lookups and whole-bundle sourcing.
- Redesign bootstrap so host capture produces a temporary intake bundle with a standalone `hardware-configuration.nix` and the host SSH `ed25519` public key.
- Make the supported host onboarding flow: copy the intake artifact into `references/host-intake/<hostname>/`, ask Codex to integrate it, then remove the temporary intake directory.
- Update repo docs and operator commands so the documented workflow matches the implemented one.

**Non-Goals:**
- Changing service behavior beyond the secret/runtime wiring needed to consume the new projected files.
- Introducing a permanent archival store for raw intake bundles under `references/host-intake/`.
- Splitting every logical-unit secret file into one file per individual scalar.
- Preserving backward compatibility for the old `sops-*` helper command surface.

## Decisions

### Use `ragenix` with SSH host `ed25519` recipients
The repo will replace `sops-nix` with `ragenix` and use SSH host `ed25519` public keys as the canonical machine recipients. This removes the current dedicated age-key bootstrap path and aligns host onboarding with keys that already exist once `sshd` is present.

Alternatives considered:
- Keep `sops-nix`: rejected because the redesign wants to move away from the monolithic encrypted YAML and the current helper workflow anyway.
- Use dedicated age keys per host: rejected because it adds another identity lifecycle and complicates bootstrap when the host already has an SSH host key.

### Store secrets by logical unit and declare them in a catalog
The repo will store encrypted files by logical unit, usually one env-shaped file per service or subsystem. `secrets/catalog.nix` will declare each unit's backing file, recipient group, file ownership/mode, format, and exported fields. This keeps editing ergonomic while still shrinking the rekey and review scope compared to one repo-wide secret file.

Alternatives considered:
- One encrypted file for the entire fleet: rejected because it preserves the current review and rekey blast radius.
- One encrypted file per scalar value: rejected because the edit workflow is too annoying for the amount of related service data in this repo.

### Compose recipient policy separately in `recipients.nix`
`secrets/recipients.nix` will define individual host and operator keys plus reusable recipient groups such as server-only, develop-only, or all-host sets. `catalog.nix` references those groups instead of repeating raw keys. This makes host onboarding and rekeying changes predictable.

Alternatives considered:
- Put recipient lists inline in every catalog entry: rejected because it duplicates policy and makes host membership changes noisy.

### Use catalog-driven projections for shared secret consumption
Shared secret usage will be modeled as projections from logical units into consumer-specific runtime files. Services will declare which exported fields they need, and a shared helper will materialize the minimal env/config surfaces they consume. This generalizes the manual projection pattern already used in `modules/self-hosted/hermes.nix` and avoids repeated direct sourcing of whole bundles in each module.

Alternatives considered:
- Keep direct file-path lookups in every module: rejected because it preserves the current sprawl and makes sharing implicit.
- Duplicate shared fields into many secret files: rejected because it increases drift and rekey overhead.

### Split bootstrap into capture and Codex-assisted integration
`bootstrap.sh` will become a capture tool that writes a temporary intake bundle containing host metadata, hardware config, and the SSH host public key. The repo-side integration step will be explicit and Codex-assisted: the operator copies the bundle into `references/host-intake/<hostname>/`, asks Codex to integrate it into `hosts/<hostname>/`, `flake.nix`, and the secret recipient model, then removes the intake directory.

Alternatives considered:
- Preserve a paste/register workflow: rejected because it embeds large artifacts in JSON and hides the real files Codex needs.
- Keep the intake directory permanently tracked: rejected because the user wants it to be temporary working state, not a long-term archive.

## Risks / Trade-offs

- [Logical-unit files can still become too broad] → Keep the default at service/subsystem granularity, then split units only when recipient sets, ownership, reuse, or churn justify it.
- [Projection helpers add abstraction over simple file paths] → Keep the catalog schema small and focus it on file metadata plus exported fields; do not turn it into a custom secret DSL.
- [Migrating every service consumer at once is cross-cutting] → Migrate catalog entries and consumer projections systematically, and verify with host-level evaluation before switching hosts.
- [SSH host keys are generated on-host and must be captured correctly] → Make bootstrap capture validate the expected `ssh_host_ed25519_key.pub` presence and fail loudly if it is missing.
- [Temporary intake bundles could be left behind] → Treat intake directory removal as part of the documented Codex integration workflow and task list.

## Migration Plan

1. Add `ragenix` to the flake and remove the global `sops-nix` module wiring.
2. Introduce `secrets/recipients.nix`, `secrets/catalog.nix`, and the initial logical-unit `.age` file layout.
3. Build a shared Nix/helper layer that can declare the secret units and render service-specific projections from exported fields.
4. Migrate existing secret data out of `secrets.yaml` into logical-unit encrypted files and update service modules to use catalog-backed projected outputs.
5. Replace `bootstrap.sh` and the old registration workflow with temporary intake bundle capture and Codex-assisted integration.
6. Update `README.md`, `CHANGELOG.md`, `AGENTS.md`, and any related workflow docs to match the new secret and host-intake workflow.
7. Verify flake evaluation for affected hosts before switching, then rebuild the relevant hosts so the new secret runtime surfaces exist.

## Open Questions

- Which operator keys, if any, should be declared alongside host SSH keys in `recipients.nix` for local editing and recovery?
- Which current secret bundles should stay combined at the subsystem level versus split further during the first migration pass?
- Whether the repo should expose a small helper command for editing catalog entries by logical secret id in addition to raw `ragenix -e <file>`.
