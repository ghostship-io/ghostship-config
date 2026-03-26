---
name: nix
description: Expert in writing Nix Flakes, packaging software, managing NixOS modules, and utilizing the nh (Nix Helper) tool. Use for any operations involving Nix configurations, flakes, packaging, or system-wide Nix/NixOS changes.
category: devops
risk: medium
source: community
date_added: "2026-02-20"
---

# Nix & NixOS Expert Skill

This skill extends Gemini CLI with specialized knowledge and workflows for Nix and NixOS, emphasizing modern patterns (Flakes) and the `nh` (Nix Helper) CLI.

## Core Directives

### 1. Unified Environment (Flakes & Direnv)
- **Always use Flakes**: Default to `flake.nix` for all project environments and configurations.
- **Direnv Integration**: Prioritize `direnv` with `nix-direnv` (e.g., `use flake`) for seamless, persistent shell activation.
- **SpecialArgs**: When defining `nixosConfigurations`, always pass `inputs` and `self` via `specialArgs` to make them available in all modules.

### 2. The `nh` (Nix Helper) Priority
For all system-level operations, prioritize the `nh` tool over raw `nix` or `nixos-rebuild` commands:
- **Rebuild & Apply**: `nh os switch` (or `nh os boot`)
- **System Test**: `nh os build`
- **Search Packages**: `nh search <query>`
- **Garbage Collection**: `nh clean all --keep 7d`

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

### 4. Validation & Testing (Pre-Deployment)
Gemini MUST always validate Nix/NixOS configurations before suggesting or applying a deployment. This ensures syntax correctness and evaluation integrity even if the target host is remote or inaccessible.
- **Syntax Check**: Use `nix-instantiate --parse <file>` for quick syntax validation.
- **Evaluation Test**: Use `nh os build` to verify that the entire NixOS configuration evaluates and builds correctly. This is the gold standard for pre-deployment validation.
- **Dry Activation**: If on a compatible system, use `nixos-rebuild dry-activate` to see what changes would be applied without modifying the system state.
- **Unit Testing**: For complex logic in modules, utilize `lib.runTests` or create a minimal flake-based test environment.

### 5. System-Wide Preferences
- **Experimental Features**: `nix-command`, `flakes`.
- **Optimization**: Enable `auto-optimise-store`.
- **Safety**: `nixpkgs.config.allowUnfree = true` (only when necessary) and `NIXPKGS_ALLOW_ALIASES = "0"`.
- **Ephemeral Run**: Use `, <command>` (comma) for one-off utility execution without permanent installation.

### 6. Surgical Configuration Manipulation (Dasel)
When a service doesn't support structured configuration directories (like `.d/`) and its config is partially managed by the app itself, use `dasel` in activation scripts to surgically inject Nix-managed settings.
- **Why**: Ensures a "Source of Truth" from Nix is applied while preserving app-managed state (e.g., sessions, dynamic preferences) that would be lost if Nix managed the whole file.
- **Availability**: `dasel` is included in `modules/common/default.nix` and is available system-wide.
- **Pattern**: Use `system.activationScripts` (NixOS) or `home.activation` (Home Manager) to run `dasel put` commands.
- **Example Usage**:
  ```nix
  system.activationScripts.myAppConfig = {
    supportsDryActivation = true;
    text = let
      dasel = "${pkgs.dasel}/bin/dasel";
      config = "/var/lib/myapp/config.yaml";
    in ''
      if [ -f "${config}" ]; then
        ${dasel} put -f ${config} -r yaml -s 'server.port' -t int -v '8080'
        ${dasel} put -f ${config} -r yaml -s 'ui.theme' -t string -v 'dark'
      fi
    '';
  };
  ```
- **Supported Formats**: `json`, `yaml`, `toml`, `xml`, `ini`, `conf`.
- **Dasel Syntax**: See `dasel --help` for selector syntax. Common selectors use dot notation (e.g., `key.subkey`).

## Workflow References

- **Flakes**: See [flake-patterns.md](references/flake-patterns.md) for boilerplate.
- **Modules**: See [module-patterns.md](references/module-patterns.md) for NixOS module structure.
- **Packaging**: See [packaging.md](references/packaging.md) for standard derivation examples.
- **NH Cheatsheet**: See [nh-reference.md](references/nh-reference.md) for quick command lookup.

## Interaction Protocol
1. **Analyze First**: Before suggesting a change, identify if it affects a Flake, a NixOS module, or a user-level configuration (Home Manager).
2. **NH Implementation**: If requested to "apply" or "rebuild", provide the `nh` command first.
3. **Brevity & Directness**: Provide code snippets followed by the specific command to execute them.
