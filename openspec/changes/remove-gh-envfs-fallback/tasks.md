## 1. Package Ownership and WSL Contract

- [x] 1.1 Move `gh` from `modules/common/default.nix` back to the shared develop `home.packages` list in `home/profiles/develop.nix`
- [x] 1.2 Remove the explicit WSL `services.envfs.extraFallbackPathCommands` entry that adds `/usr/bin/gh`
- [x] 1.3 Keep general WSL `services.envfs.enable = true` support intact while narrowing the `gh` contract

## 2. Verification

- [x] 2.1 Verify `nix eval --raw .#nixosConfigurations.launch-octopus.config.system.build.toplevel.drvPath` still succeeds after the config changes
- [x] 2.2 Verify `nix build .#nixosConfigurations.launch-octopus.config.system.build.toplevel -L` succeeds after the config changes
- [x] 2.3 Verify the evaluated host configuration includes `gh` in Home Manager, excludes it from the shared system baseline, and omits the `envfs` fallback command for `gh`

## 3. Documentation

- [x] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe `gh` as develop-profile user tooling
- [x] 3.2 Remove documentation that claims the repo manages `/usr/bin/gh` through WSL `envfs`
