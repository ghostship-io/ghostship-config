## 1. Package agent-deck

- [ ] 1.1 Add a local Nix derivation for the upstream tagged `agent-deck` release and wire it into the repo’s package/overlay structure.
- [ ] 1.2 Verify the derivation builds the `agent-deck` CLI without relying on the upstream installer or `go install`.

## 2. Wire the develop profile

- [ ] 2.1 Add `agent-deck` to the shared develop Home Manager package list.
- [ ] 2.2 Add `tmux` to the shared develop Home Manager package list if it is not already present so `agent-deck` has its required runtime dependency.

## 3. Update docs and verification

- [ ] 3.1 Update active documentation, including `README.md` and `AGENTS.md`, to describe `agent-deck` as a repo-managed develop-profile tool and note that activation requires the relevant rebuild or switch.
- [ ] 3.2 Add a `CHANGELOG.md` entry for repo-managed `agent-deck` packaging.
- [ ] 3.3 Run concrete verification for the packaging and profile wiring, including a Nix evaluation/build command such as `nix build .#homeConfigurations.nixos.activationPackage -L` or the repo’s equivalent host/home validation path, and confirm the resulting configuration includes `agent-deck`.
