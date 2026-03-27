---
name: nix
description: Expert in writing Nix Flakes, packaging software, managing NixOS modules, and using native Nix commands. Use for any operations involving Nix configurations, flakes, packaging, or system-wide Nix/NixOS changes.
category: devops
risk: medium
source: community
date_added: "2026-02-20"
---

# Nix & NixOS Expert Skill

This skill extends Gemini CLI with specialized knowledge and workflows for Nix and NixOS, emphasizing modern patterns (Flakes) and native `nix` commands.

## Core Directives

### 1. Unified Environment (Flakes & Direnv)
- **Always use Flakes**: Default to `flake.nix` for all project environments and configurations.
- **Direnv Integration**: Prioritize `direnv` with `nix-direnv` (e.g., `use flake`) for seamless, persistent shell activation.
- **SpecialArgs**: When defining `nixosConfigurations`, always pass `inputs` and `self` via `specialArgs` to make them available in all modules.

### 2. Native Nix Operations
For system-level validation, use standard `nix` and `nixos-rebuild` commands. You MUST NEVER apply configurations (switch/boot) automatically; always build to verify validity:
- **System Validation (Build)**: `nixos-rebuild build --flake .`
- **Search Packages**: `nix search nixpkgs <query>`
- **Garbage Collection**: `sudo nix-collect-garbage -d`

### 3. Idiomatic Nix Development
- **Packaging**:
    - Use appropriate builder helpers: `stdenv.mkDerivation`, `buildPythonPackage`, `buildNpmPackage`, `buildGoModule`, `buildRustPackage`.
    - Avoid hardcoding `/bin/` paths; use `${pkgs.package}/bin/cmd`.
    - Handle dynamic linking with `nix-ld` when necessary.
- **Modules**:
    - Structure modules with clear `options` and `config` separation.
    - Use `lib.types` for strictly typed options.
    - Prefer `mkIf` and `mkEnableOption` for conditional logic.
- **Wrappers**:
    - Use `writeShellScriptBin` or `symlinkJoin` to create system-wide wrappers (e.g., `dig` -> `drill`, `vim` -> `nvim`).

### 4. Validation & Testing (MANDATORY)
The AGENT MUST always validate Nix/NixOS configurations. You are NOT permitted to apply or deploy changes; your responsibility ends at providing verified, buildable code.
- **Syntax Check**: Use `nix-instantiate --parse <file>` for quick syntax validation.
- **Evaluation Test (THE GOLD STANDARD)**: Use `nixos-rebuild build --flake .` to verify that the entire NixOS configuration evaluates and builds correctly. This MUST be performed before claiming success.
- **Unit Testing**: For complex logic in modules, utilize `lib.runTests` or create a minimal flake-based test environment.

### 5. System-Wide Preferences
- **Experimental Features**: `nix-command`, `flakes`.
- **Optimization**: Enable `auto-optimise-store`.
- **Safety**: `nixpkgs.config.allowUnfree = true` (only when necessary) and `NIXPKGS_ALLOW_ALIASES = "0"`.
- **Ephemeral Run**: Use `nix shell nixpkgs#<package> -c <command>` for one-off utility execution or testing when a program or library is not available in the current environment.

### 6. Surgical Configuration Manipulation (ghostship-config)
When a service doesn't support structured configuration directories (like `.d/`) and its config is partially managed by the app itself, use `ghostship-config` in activation scripts to surgically inject Nix-managed settings.
- **Why**: Ensures a "Source of Truth" from Nix is applied while preserving app-managed state (e.g., sessions, dynamic preferences) that would be lost if Nix managed the whole file.
- **Pattern**: Use `system.activationScripts` (NixOS) or `home.activation` (Home Manager) to run `ghostship-config set` commands.
- **Example Usage**:
  ```nix
  system.activationScripts.myAppConfig = {
    text = let
      config = "/var/lib/myapp/config.yaml";
    in ''
      if [ -f "${config}" ]; then
        ${pkgs.ghostship-config}/bin/ghostship-config set "${config}" \
          "server.port=yaml:8080" \
          "ui.theme=literal:dark"
      fi
    '';
  };
  ```
- **Supported Formats**: `json`, `yaml`, `toml`, `xml`, `ini`, `conf`.

## Workflow References

- **Flakes**: See [flake-patterns.md](references/flake-patterns.md) for boilerplate.
- **Modules**: See [module-patterns.md](references/module-patterns.md) for NixOS module structure.
- **Packaging**: See [packaging.md](references/packaging.md) for standard derivation examples.

## Interaction Protocol
1. **Analyze First**: Before suggesting a change, identify if it affects a Flake, a NixOS module, or a user-level configuration (Home Manager).
2. **Validation First**: Always provide the `nixos-rebuild build --flake .` command alongside your changes to ensure the user can verify them.
3. **Brevity & Directness**: Provide code snippets followed by the specific command to validate them.
