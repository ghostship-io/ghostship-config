## 1. Managed Paseo Tooling

- [x] 1.1 Add a managed `paseo` wrapper in the develop agent-tooling layer and expose it through the develop host package flow.
- [x] 1.2 Extend `ghostship-agent-maintenance` to install and refresh `@getpaseo/cli` in the managed user-local npm prefix.
- [x] 1.3 Verify the managed wrapper and maintenance script both resolve Paseo from `/home/nixos/.local/share/ghostship-agent-tools/npm`.

## 2. WSL Runtime Wiring

- [x] 2.1 Add a WSL-only systemd service for the managed Paseo daemon that runs as `nixos`, uses a stable `PASEO_HOME`, and starts Paseo in foreground mode with explicit listen settings.
- [x] 2.2 Add explicit WSL `npm` and `npx` compatibility wrappers that exec the real Nix store binaries instead of the broken raw launcher shims.
- [x] 2.3 Verify the evaluated WSL host config declares the Paseo daemon service and the wrapper-backed `npm` / `npx` compatibility paths.

## 3. Docs And Verification

- [x] 3.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to document the managed Paseo workflow, Windows desktop attachment path, version-lockstep caveat, and wrapper-backed `npm` / `npx` contract.
- [x] 3.2 Run `nixos-rebuild build --flake .#launch-octopus -L` and `nixos-rebuild build --flake .#armored-armadillo -L` to verify the shared WSL changes evaluate and build cleanly.
- [x] 3.3 After activation on a target WSL host, verify `ghostship-agent-maintenance` installs Paseo, the managed daemon service starts successfully, and the supported desktop-connection target is documented accurately.
