## 1. Reproduce And Isolate

- [ ] 1.1 Continue binary-splitting current default dev shell package set until minimal failing combination is confirmed.
- [ ] 1.2 Capture evidence comparing a working near-full shell against failing full shell so root trigger is explicit before mitigation.

## 2. Repo Mitigation

- [ ] 2.1 Update `flake.nix` so repo default dev shell avoids failing environment export path while keeping required tooling repo-managed.
- [ ] 2.2 If any tool must leave default shell, add explicit replacement access path or revised supported workflow in repo-managed docs.

## 3. Verification

- [ ] 3.1 Run `nix build -L .#devShells.x86_64-linux.default` and `nix print-dev-env -L .#default` to verify shell derivation and environment export both succeed.
- [ ] 3.2 Run `nix develop .#default --command bash -lc 'printf ok'` and `direnv reload` from repo root to verify real developer entrypoints no longer fail or fall back.

## 4. Documentation

- [ ] 4.1 Update `README.md` with repaired dev-shell workflow, any refresh step, and any remaining caveat tied to current Nix behavior.
- [ ] 4.2 Update `CHANGELOG.md` and `AGENTS.md` with durable notes about default dev-shell behavior and any documented workaround or constraint.
