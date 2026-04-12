## Why

This repo's current secrets and host-bootstrap workflow is too tightly coupled to `sops-nix`, a single repo-wide `secrets.yaml`, and a paste-oriented registration flow that mixes host identity, hardware config capture, and secret recipient management. That makes secret review and rekeying coarse-grained, keeps shared-secret wiring scattered across service modules, and gives Codex poor artifacts to use when integrating a new host.

The repo needs a redesign now because the migration to `ragenix` is an opportunity to replace the current monolith with logical-unit secret files, a catalog-driven sharing model, and a temporary host-intake workflow that is explicitly designed for Codex-assisted integration.

## What Changes

- Replace `sops-nix`, `.sops.yaml`, and the repo-wide encrypted `secrets.yaml` workflow with `ragenix`, `secrets/recipients.nix`, `secrets/catalog.nix`, and logical-unit `.age` files.
- Standardize secret recipients on SSH host `ed25519` public keys plus any declared operator keys, with reusable recipient groups composed in `recipients.nix`.
- Introduce a secrets catalog that declares each logical secret unit's encrypted file, recipient group, ownership, mode, format, and exported fields.
- Add a shared projection layer so services consume only the secret fields they need instead of open-coding many `config.sops.secrets.*.path` references and sourcing whole bundles ad hoc.
- Redesign bootstrap so host capture produces a temporary intake artifact bundle containing host metadata, the standalone `hardware-configuration.nix`, and the host SSH `ed25519` public key.
- Replace the old paste/register workflow with a Codex-assisted flow: copy the intake artifact into `references/host-intake/<hostname>/`, ask Codex to integrate it, then remove the temporary intake directory after integration.
- Remove legacy `sops-*` helper tooling, the old plaintext mirror workflow, and stale docs that reference the pre-redesign commands.

## Capabilities

### New Capabilities
- `secret-catalog`: Define logical-unit encrypted secret files through a central catalog and recipient model backed by `ragenix`.
- `service-secret-projections`: Project only the required secret fields into service-specific env/config surfaces so shared secret data is wired declaratively instead of by repeated raw file sourcing.
- `host-intake-bootstrap`: Capture host bootstrap artifacts into a temporary intake bundle that Codex can read to integrate a new host into the repo.

### Modified Capabilities
- None.

## Impact

- Affected systems: develop hosts, server hosts, Home Manager docs and wrappers, and repo-only workflow files.
- Affected code: `flake.nix`, `bootstrap.sh`, `modules/common/secrets.nix`, `modules/self-hosted/secrets.nix`, many `modules/self-hosted/*.nix` consumers, new `secrets/` metadata and encrypted files, and temporary `references/host-intake/` workflow assets.
- Dependencies: replace `sops-nix` with `ragenix`; continue to use native `nix`, `nixos-rebuild`, and `switch-to-configuration` workflows.
- Manual implications: all hosts will need a rebuild to pick up the new secret runtime wiring; the repo will need a one-time migration from `secrets.yaml` into logical-unit `.age` files; operators will stop using the old `sops-*` commands; temporary host-intake directories under `references/host-intake/` must be removed after Codex finishes integration.
