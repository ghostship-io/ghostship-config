## 1. Hermes module alignment

- [x] 1.1 Remove the legacy Hermes startup shim from `modules/self-hosted/hermes.nix`, including the custom startup script, `entrypoint`, `cmd`, hardcoded runtime store path, separate `.honcho` bind mount, and writable `/nix` volume.
- [x] 1.2 Preserve the native Hermes durable state mount by keeping `/srv/apps/hermes/home` mounted at `/home/hermes/.hermes` and leaving the current env and secret wiring intact unless testing proves otherwise.
- [x] 1.3 Add a one-time migration path that moves or copies `/srv/apps/hermes/home/.honcho/config.json` into `/srv/apps/hermes/home/shared/honcho/config.json` before the native image startup path takes over.

## 2. Nix verification

- [x] 2.1 Parse-check `modules/self-hosted/hermes.nix` with `nix-instantiate --parse modules/self-hosted/hermes.nix`.
- [x] 2.2 Verify the generated Hermes container config with `nix eval .#nixosConfigurations.chill-penguin.config.virtualisation.oci-containers.containers.hermes`.
- [x] 2.3 Verify the host still evaluates after the Hermes changes with `nix flake check --no-build` and note the expected `aarch64-linux` limitation from this workspace.

## 3. Documentation

- [x] 3.1 Update `README.md` to describe that Hermes now relies on the image's native entrypoint and layout.
- [x] 3.2 Update `CHANGELOG.md` with the Hermes native-layout migration and removal of repo-side image overrides.
- [x] 3.3 Record the native Hermes image contract and Honcho migration expectation in `AGENTS.md`.

## 4. Host cutover validation

- [x] 4.1 Apply the rebuilt config on `chill-penguin` using the repo's preferred deploy flow.
- [x] 4.2 Verify the live container uses the image's native startup contract with `podman inspect hermes` and `systemctl status podman-hermes.service --no-pager`.
- [x] 4.3 Verify the migrated Honcho config is available through the native Hermes layout and that the legacy bind-mounted path is no longer required.
