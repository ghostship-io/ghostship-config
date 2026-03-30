# Project Workflow

## Principles

1. Use native `nix` and `nixos-rebuild` as the supported workflow.
2. Verify changes empirically before claiming they work.
3. Keep `AGENTS.md`, `README.md`, and `CHANGELOG.md` aligned with the code.
4. Prefer existing NixOS and Home Manager abstractions over ad hoc shell logic.
5. Keep host behavior role-driven instead of branching on hostnames.

## Implementation Flow

1. Read the relevant modules and confirm the current behavior.
2. Make the smallest coherent change that fixes the issue or improves the
   structure.
3. Re-run the narrowest useful verification first.
4. Re-run host-level flake evaluation before closing out structural changes.
5. Update docs when behavior, layout, or operator workflow changes.
6. Commit logically with a scoped message.

## Verification

For structural Nix changes, prefer:

```bash
nix eval --raw .#nixosConfigurations.<host>.config.system.build.toplevel.drvPath
```

For deployable hosts, build before switching:

```bash
nixos-rebuild build --flake .#<host>
./result/bin/switch-to-configuration switch
```

## Secrets

- Edit the plaintext mirror in `secrets.dec.yaml`.
- Re-encrypt into `secrets.yaml` before committing encrypted secret changes.
- Keep service-local bundles in `*-secrets` blocks.

## Package Ownership

- `environment.systemPackages`: admin tools, diagnostics, runtime dependencies,
  and a small system-wide baseline.
- `home.packages`: interactive user tooling and shell UX.

## Shell Policy

- Server-role hosts default to `bash` and keep the home profile minimal.
- Develop-role hosts default to `fish` and carry the richer interactive setup.
- WSL-specific shell additions belong in the WSL profile layer only.
