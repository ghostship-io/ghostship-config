# Implementation Plan: Bootstrap SOPS Key Generation

## Phase 1: Implementation
- [x] Task: Define the high-priority activation script. 7ca3562
- [x] Task: Create a dedicated `modules/common/bootstrap.nix` module.
- [x] Task: Move bootstrap logic from `secrets.nix` to `bootstrap.nix`.
- [x] Task: Implement `nixos-generate-config` logic to create a temporary hardware-configuration.nix.
- [x] Task: Output the location of the generated hardware config and the public key.
- [x] Task: Ensure hostname is set and added as a dependency.
- [x] Task: Validate configuration with nix flake check.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Implementation' (Protocol in workflow.md)

## Phase 2: Verification
- [ ] Task: Test the bootstrap process by temporarily moving the existing age key on the current host.
- [ ] Task: Verify that the public key is correctly displayed and the build halts as expected.
- [ ] Task: Verify that after restoring the key (or adding the new one) and re-applying, the build completes successfully.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Verification' (Protocol in workflow.md)

## Phase 3: Documentation
- [x] Task: Document the bootstrap setup flow in README.md.
- [x] Task: Update CHANGELOG.md with the new bootstrap feature.
- [x] Task: Conductor - User Manual Verification 'Phase 3: Documentation' (Protocol in workflow.md)
