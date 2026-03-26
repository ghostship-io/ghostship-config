# Specification: Bootstrap SOPS Key Generation for New Hosts

## Overview
When bootstrapping a new host, the sops-nix age key is often missing, leading to build failures. This feature will automatically generate an age key if it's missing during the NixOS activation phase, display the public key to the user, and halt the activation process to allow the user to add the key to the project's secrets configuration.

## Functional Requirements
- **Automatic Detection:** A NixOS activation script will check for the existence of the age key at `${homeDir}/.local/state/sops-nix/sops-age.key`.
- **Automatic Generation:** If the key is missing, the script will use `age-keygen` to generate a new key.
- **High-Priority Execution:** The script will be defined as a high-priority NixOS activation script to ensure it runs *before* other modules (like `sops-nix`) that depend on the existence of the decrypted secrets.
- **Terminal Notification:** The script will output a clear message to the terminal containing the newly generated public key.
- **Halt on First Run:** After generating the key and displaying the public key, the activation script will exit with a failure code to prevent the rest of the activation (including sops-nix decryption) from proceeding with a missing or unconfigured key.
- **Instructional Guidance:** The terminal output will provide the next steps (adding the key to `.sops.yaml`, re-encrypting `secrets.yaml`, and re-applying the configuration).

## Non-Functional Requirements
- **Idempotency:** On subsequent runs where the key already exists, the script will do nothing and exit successfully.
- **Security:** Ensure the generated key file has the correct permissions (600).

## Acceptance Criteria
- [ ] Running `nixos-rebuild switch` on a system without an age key triggers the generation.
- [ ] The public key is clearly visible in the terminal output.
- [ ] The build fails with a descriptive message after generating the key.
- [ ] After adding the key to the repository and re-applying, the build completes successfully.

## Out of Scope
- Automatically committing or pushing the public key to the repository.
- Handling multiple keys for the same host.
