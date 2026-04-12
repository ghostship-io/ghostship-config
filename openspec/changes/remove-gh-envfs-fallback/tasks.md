## 1. Package Ownership and WSL Contract

- [ ] 1.1 Move `gh` from `modules/common/default.nix` back to the shared develop `home.packages` list in `home/profiles/develop.nix`
- [ ] 1.2 Remove the explicit WSL `services.envfs.extraFallbackPathCommands` entry that adds `/usr/bin/gh`
- [ ] 1.3 Keep general WSL `services.envfs.enable = true` support intact while narrowing the `gh` contract

## 2. Verification

- [ ] 2.1 Verify `nix eval --raw .#nixosConfigurations.launch-octopus.config.system.build.toplevel.drvPath` still succeeds after the config changes
- [ ] 2.2 Verify `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L` succeeds after the config changes
- [ ] 2.3 Verify the evaluated host configuration includes `gh` in Home Manager, excludes it from the shared system baseline, and omits the `envfs` fallback command for `gh`

## 3. Documentation

- [ ] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe `gh` as develop-profile user tooling
- [ ] 3.2 Remove documentation that claims the repo manages `/usr/bin/gh` through WSL `envfs`
