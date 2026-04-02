## 1. Explicit Launcher Defaults

- [x] 1.1 Update the generated Codex config to set `approval_policy = "never"` and `sandbox_mode = "danger-full-access"` for develop hosts.
- [x] 1.2 Update Gemini and both OpenCode config definitions so Gemini defaults to `yolo` and OpenCode explicitly sets `permission = "allow"` in both the system and Home Manager config paths.

## 2. Documentation And Verification

- [x] 2.1 Update `README.md`, `CHANGELOG.md`, and `AGENTS.md` to describe the new develop-host launcher defaults and required activation steps.
- [x] 2.2 Verify the generated configs with `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."codex/config.toml".text'`, `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."gemini-cli/settings.json".text'`, `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.environment.etc."opencode/opencode.json".text'`, and `nix eval --raw '.#nixosConfigurations.armored-armadillo.config.home-manager.users.nixos.home.file.".config/opencode/opencode.json".text'`.
