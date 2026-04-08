## 1. Package workmux

- [ ] 1.1 Choose and implement the repo-managed Nix packaging path for
  `workmux` from a pinned upstream source.
- [ ] 1.2 Verify the chosen packaging path provides the `workmux` CLI without
  relying on upstream's installer script or `cargo install`.

## 2. Wire the develop profile

- [ ] 2.1 Add `workmux` to the shared develop Home Manager package list.
- [ ] 2.2 Confirm the shared configuration already provides the required
  runtime baseline for the repo-supported path, especially `git` and `tmux`, so
  no duplicate Home Manager entries are needed.
- [ ] 2.3 Keep the repo-supported backend scope explicit by documenting the
  initial `tmux`-first workflow boundary.

## 3. Document and verify

- [ ] 3.1 Update active documentation, including `README.md` and `AGENTS.md`, to
  describe `workmux` as a repo-managed develop-profile tool and note that
  activation requires the relevant rebuild or switch.
- [ ] 3.2 Add a `CHANGELOG.md` entry for repo-managed `workmux` packaging.
- [ ] 3.3 Run concrete verification for the packaging and profile wiring,
  including a Nix evaluation/build command such as
  `nix build .#homeConfigurations.nixos.activationPackage -L` or the repo's
  equivalent validation path, and confirm the resulting configuration includes
  `workmux`.
