## 1. Package agent-deck

- [x] 1.1 Add a local Nix derivation for the upstream tagged `agent-deck` release and wire it into the repo’s package/overlay structure.
- [x] 1.2 Verify the derivation builds the `agent-deck` CLI without relying on the upstream installer or `go install`.

## 2. Wire the develop profile

- [x] 2.1 Add `agent-deck` to the shared develop Home Manager package list.
- [x] 2.2 Confirm the shared configuration already provides `tmux` for `agent-deck`, so no duplicate Home Manager entry is needed.

## 3. Update docs and verification

- [x] 3.1 Update active documentation, including `README.md` and `AGENTS.md`, to describe `agent-deck` as a repo-managed develop-profile tool and note that activation requires the relevant rebuild or switch.
- [x] 3.2 Add a `CHANGELOG.md` entry for repo-managed `agent-deck` packaging.
- [x] 3.3 Run concrete verification for the packaging and profile wiring, including a Nix evaluation/build command such as `nix build .#homeConfigurations.nixos.activationPackage -L` or the repo’s equivalent host/home validation path, and confirm the resulting configuration includes `agent-deck`.
