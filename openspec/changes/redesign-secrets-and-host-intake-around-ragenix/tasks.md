## 1. Ragenix Foundation

- [ ] 1.1 Add `ragenix` to `flake.nix`, remove the global `sops-nix` module wiring, and expose any required `ragenix` CLI/package support in the repo shell or host tooling.
- [ ] 1.2 Create the new `secrets/` layout with `recipients.nix`, `catalog.nix`, and the initial logical-unit encrypted file tree.
- [ ] 1.3 Define reusable recipient groups in `secrets/recipients.nix` using SSH host `ed25519` public keys plus any declared operator keys.
- [ ] 1.4 Replace the old `modules/common/secrets.nix` runtime wiring so the repo's base secret support reads from the new catalog-driven `ragenix` model instead of `sops.*`.

## 2. Secret Catalog And Projection Layer

- [ ] 2.1 Implement a shared Nix/helper layer that materializes catalog-defined logical secret units and their projected consumer surfaces.
- [ ] 2.2 Convert current secret storage from the monolithic `secrets.yaml` into logical-unit `.age` files grouped by service or subsystem rather than by scalar.
- [ ] 2.3 Update `modules/self-hosted/secrets.nix` to declare the new logical units and projection outputs instead of individual `sops.secrets.*` entries.
- [ ] 2.4 Migrate shared-secret consumers such as Homepage, Hermes, Bazarr, Recyclarr, Tautulli, and related modules to use projected outputs instead of repeated raw secret file path lookups and ad hoc bundle sourcing.
- [ ] 2.5 Remove `.sops.yaml`, `secrets.yaml`, the plaintext mirror workflow, and the legacy `sops-*` helper commands once the new catalog and projection flow is complete.

## 3. Host Intake Redesign

- [ ] 3.1 Replace `bootstrap.sh` with a capture workflow that writes a temporary host intake bundle containing metadata, standalone `hardware-configuration.nix`, and the host SSH `ed25519` public key.
- [ ] 3.2 Add the repo-side temporary intake staging workflow under `references/host-intake/<hostname>/` for Codex-assisted host integration.
- [ ] 3.3 Implement or document the Codex-assisted integration flow that consumes staged intake artifacts to update `hosts/<hostname>/`, `flake.nix`, and `secrets/recipients.nix`.
- [ ] 3.4 Ensure the documented workflow removes temporary intake directories after Codex finishes integrating the host.

## 4. Verification

- [ ] 4.1 Run targeted verification for the new secret catalog/projection layer, including any helper/unit checks needed to confirm projected outputs contain only declared fields.
- [ ] 4.2 Run `nix eval --raw .#nixosConfigurations.launch-octopus.config.system.build.toplevel.drvPath` and `nix eval --raw .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath` to verify the redesigned secret plumbing evaluates for both a develop host and a server host.
- [ ] 4.3 Run `nixos-rebuild build --flake .#launch-octopus` and `nixos-rebuild build --flake .#chill-penguin` to verify the new runtime secret surfaces and bootstrap wiring build cleanly for representative hosts.

## 5. Documentation And Workflow Cleanup

- [ ] 5.1 Update `README.md` with the new `ragenix`, logical-unit secret, projection, and temporary host-intake workflow.
- [ ] 5.2 Update `AGENTS.md` with durable repo memory for the new recipient model, secret catalog/projection pattern, and Codex-assisted host onboarding flow.
- [ ] 5.3 Update `CHANGELOG.md` to document the migration away from `sops-nix`, the new logical-unit secret catalog, and the temporary intake workflow.
