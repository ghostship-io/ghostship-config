## 1. Wrapper-Managed Model Refresh

- [x] 1.1 Add OpenCode prelaunch logic in `modules/develop/agent-tooling.nix` that fetches `https://openrouter.ai/api/frontend/models/find?categories=programming&fmt=cards&max_price=0&order=top-weekly`, filters the returned models by free pricing, and writes a generated OpenCode config once per day.
- [x] 1.2 Update the OpenCode launcher definitions to export `OPENCODE_CONFIG` to the generated config before executing `opencode-ai`, while preserving the existing warning-only preflight behavior and fallback to the last good generated config.

## 2. Static Config Removal

- [x] 2.1 Remove the static `provider.openrouter.models` definitions from `modules/develop/opencode-wrapper.nix` and `modules/develop/opencode.nix`, keeping explicit `permission = "allow"` defaults intact in both config paths.
- [x] 2.2 Verify the generated static configs no longer embed OpenRouter model maps with `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."opencode/opencode.json".text'` and `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.home-manager.users.nixos.home.file.".config/opencode/opencode.json".text'`.

## 3. Verification And Documentation

- [x] 3.1 Build and inspect the develop-host launcher output to confirm the wrapper exports `OPENCODE_CONFIG` and contains the daily refresh logic, using `nix build .#nixosConfigurations.armored-armadillo.config.system.build.toplevel -L` and inspecting `./result/sw/bin/opencode`.
- [x] 3.2 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe the daily programming-free model refresh flow, the removal of static OpenCode model lists, and the required NixOS rebuild or Home Manager switch activation scope.
