## 1. WSL PATH Contract

- [x] 1.1 Update `modules/wsl/wsl.nix` so WSL interop stays enabled but `wsl.wslConf.interop.appendWindowsPath = false`.
- [x] 1.2 Verify the WSL module still preserves the intended `envfs`-backed Linux/FHS behavior such as `/usr/bin/bash`.

## 2. Explicit Windows Entry Points

- [x] 2.1 Replace raw `pkgs.wsl-open` in `home/profiles/wsl.nix` with a wrapped `wsl-open` package that exports `PowershellExe=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`.
- [x] 2.2 Add the minimum explicit Windows PowerShell entrypoint needed for repo-managed WSL workflows, and update any repo-managed callers that still depend on bare PATH-based `powershell.exe` lookup.
- [x] 2.3 Audit repo-managed WSL docs and helper references for bare Windows PATH command assumptions and narrow them to the supported explicit contract.

## 3. Documentation

- [x] 3.1 Update `README.md` to explain that WSL hosts keep `envfs` for Linux/FHS paths but use explicit wrappers or explicit `/mnt/c/...` paths for supported Windows tools.
- [x] 3.2 Update `AGENTS.md` with durable repo memory for the explicit Windows interop contract and the reason `appendWindowsPath` stays disabled.
- [x] 3.3 Update WSL skill/reference docs such as `home/config/skills/wsl2/references/interop-tools.md` so they no longer recommend bare `powershell.exe` from PATH.
- [x] 3.4 Update `CHANGELOG.md` to record the narrowed, explicit Windows interop contract on WSL hosts.

## 4. Verification

- [x] 4.1 Run `nix eval --raw .#nixosConfigurations.armored-armadillo.config.system.build.toplevel.drvPath` to verify the WSL host evaluates with the narrowed PATH contract.
- [x] 4.2 Run `nixos-rebuild build --flake .#armored-armadillo -L` to verify the WSL host build includes the new envfs and explicit-wrapper wiring.
- [x] 4.3 Verify `wsl-open -x .` resolves to `/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe` instead of `/usr/bin/powershell.exe`.
- [x] 4.4 Verify `open .` no longer fails with `/usr/bin/powershell.exe: Invalid argument`, and verify Linux/FHS compatibility still works for representative paths such as `/usr/bin/bash`.
