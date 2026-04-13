## 1. Ragenix Foundation

- [x] 1.1 Add `ragenix` to `flake.nix`, remove the global `sops-nix` module wiring, and expose any required `ragenix` CLI/package support in the repo shell or host tooling.
- [x] 1.2 Create the new `secrets/` layout with `recipients.nix`, `catalog.nix`, and the initial logical-unit encrypted file tree.
- [x] 1.3 Define reusable recipient groups in `secrets/recipients.nix` using SSH host `ed25519` public keys plus the dedicated passwordless non-default operator edit key.
- [x] 1.4 Define and document the standard location and setup flow for the dedicated passwordless operator edit key, keeping it separate from the user's default SSH key.
- [x] 1.5 Replace the old `modules/common/secrets.nix` runtime wiring so the repo's base secret support reads from the new catalog-driven `ragenix` model instead of `sops.*`.

## 2. Secret Catalog And Projection Layer

- [x] 2.1 Implement a shared Nix/helper layer that materializes catalog-defined logical secret units and their projected consumer surfaces.
- [x] 2.2 Convert current secret storage from the monolithic `secrets.yaml` into logical-unit `.age` files grouped by service or subsystem rather than by scalar.
- [x] 2.3 Update `modules/self-hosted/secrets.nix` to declare the new logical units and projection outputs instead of individual `sops.secrets.*` entries.
- [x] 2.4 Migrate shared-secret consumers such as Homepage, Hermes, Bazarr, Recyclarr, Tautulli, and related modules to use projected outputs instead of repeated raw secret file path lookups and ad hoc bundle sourcing.
- [x] 2.5 Remove `.sops.yaml`, `secrets.yaml`, and the legacy `sops-*` helper commands while retaining the plaintext mirror workflow as the normal edit surface.

## 3. Host Intake Redesign

- [x] 3.1 Replace `bootstrap.sh` with a capture workflow that writes a temporary host intake bundle containing metadata, standalone `hardware-configuration.nix`, and the host SSH `ed25519` public key.
- [x] 3.2 Ensure the capture workflow generates or validates the SSH host `ed25519` key on WSL2 hosts before writing the intake bundle.
- [x] 3.3 Add the repo-side temporary intake staging workflow under `references/host-intake/<hostname>/` for Codex-assisted host integration.
- [x] 3.4 Implement or document the Codex-assisted integration flow that consumes staged intake artifacts to update `hosts/<hostname>/`, `flake.nix`, and `secrets/recipients.nix`.
- [x] 3.5 Ensure the documented workflow removes temporary intake directories after Codex finishes integrating the host.

## 4. Verification

- [x] 4.1 Run targeted verification for the new secret catalog/projection layer, including any helper/unit checks needed to confirm projected outputs contain only declared fields.
- [x] 4.2 Run `nix eval --raw .#nixosConfigurations.launch-octopus.config.system.build.toplevel.drvPath` and `nix eval --raw .#nixosConfigurations.chill-penguin.config.system.build.toplevel.drvPath` to verify the redesigned secret plumbing evaluates for both a develop host and a server host.
- [ ] 4.3 Run `nixos-rebuild build --flake .#launch-octopus` and `nixos-rebuild build --flake .#chill-penguin` to verify the new runtime secret surfaces and bootstrap wiring build cleanly for representative hosts.
  Note: `launch-octopus` built successfully. `chill-penguin` evaluates and dry-runs successfully here, but a full local build still stops on the expected `aarch64-linux` requirement from this `x86_64-linux` machine.

## 5. Documentation And Workflow Cleanup

- [x] 5.1 Update `README.md` with the new `ragenix`, logical-unit secret, projection, and temporary host-intake workflow.
- [x] 5.2 Update `AGENTS.md` with durable repo memory for the new recipient model, secret catalog/projection pattern, and Codex-assisted host onboarding flow.
- [x] 5.3 Update `CHANGELOG.md` to document the migration away from `sops-nix`, the new logical-unit secret catalog, and the temporary intake workflow.
