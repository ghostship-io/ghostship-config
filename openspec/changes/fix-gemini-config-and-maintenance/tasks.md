## 1. Gemini Config Cleanup

- [x] 1.1 Remove the deprecated `experimental.plan` setting from `modules/develop/gemini.nix` while keeping the generated Gemini settings valid for the current CLI release.
- [x] 1.2 Add or adjust verification so the generated `gemini-cli/settings.json` no longer contains `experimental.plan`.

## 2. Maintenance Runtime Repair

- [x] 2.1 Update the develop-host maintenance wiring in `modules/develop/agent-tooling.nix` and related service definitions so npm and npx subprocesses have an executable `sh` and the intended managed runtime environment under systemd.
- [x] 2.2 Verify the generated maintenance script or service environment still targets `/home/nixos/.local/share/ghostship-agent-tools/npm` and no longer fails refresh steps with `spawn sh ENOENT`.

## 3. Verification and Documentation

- [x] 3.1 Run concrete Nix verification for the affected develop-host configuration, including at least `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."gemini-cli/settings.json".text'` and any needed inspection of the generated `ghostship-agent-maintenance` script or unit.
- [ ] 3.2 If architecture and host fit allow it, run an appropriate build or host-side verification path for the affected develop-host configuration and confirm Gemini starts without the deprecated-settings warning after the change is live.
- [x] 3.3 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the Gemini config cleanup, maintenance runtime expectations, and any rebuild or rerun requirements for activation.
