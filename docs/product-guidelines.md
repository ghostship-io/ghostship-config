# Product Guidelines: Unified NixOS Configuration Repository

## Core Mandates
- **Modular Design**: Maintain strict separation between hardware-specific logic in `hosts/`, shared system modules in `modules/`, and user-level configurations in `home/`.
- **Absolute Reproducibility**: Every system must be rebuildable from scratch to an identical state using the declarative Nix configuration.
- **Security First**: No secrets in plain text. All sensitive data (API keys, passwords, credentials) must be managed through `sops-nix`.
- **Literate Documentation**: Provide clear inline rationale for non-trivial Nix expressions and maintain up-to-date documentation in the `docs/` directory.

## Documentation Standards
- **Inline Rationale**: All non-trivial Nix expressions MUST include detailed inline comments explaining the *intent* and any "gotchas" discovered during implementation.
- **Literate Exploration**: For complex subsystems (e.g., custom secrets logic or complex desktop environments), consider using literate programming techniques or dedicated Markdown overviews to bridge the gap between code and documentation.

## Repository Organization
- **Standard Modular Structure**: The repository will follow a clear, top-level directory structure to separate concerns:
    - `hosts/`: Host-specific configurations and hardware definitions.
    - `modules/`: Shared system-level NixOS modules (nixosModules).
    - `home/`: User-level configurations (home-manager modules).
    - `lib/`: Helper functions and Nix utility logic.
    - `pkgs/`: Custom packages or overlays.
- **Mixed-Platform Fleet Architecture**:
    - The repository is designed to support a heterogeneous fleet (e.g., WSL2 instances and Bare Metal installs like Mac Studio).
    - **Common Logic**: Shared settings (locale, core packages, automation) MUST reside in `modules/common/` and be platform-agnostic.
    - **Platform Integration**: Environmental integrations (e.g., `nixos-wsl`, hardware-specific bootloaders) MUST be handled at the host level or via specialized platform modules, never in the common core.
- **Flake Integration**: The root `flake.nix` will serve as the primary entry point, cleanly exposing `nixosConfigurations`, `homeConfigurations`, and `devShells`.

## User Experience (UX) & Environment
- **Feature-Rich CLI**: The default user environment should be optimized for productivity, featuring a robust shell (e.g., Zsh or Fish), modern CLI replacements (e.g., `bat`, `eza`, `fd`), and pre-configured development tools.
- **Developer-Centric Focus**: Prioritize tools and aliases that streamline Nix-related tasks (e.g., `nh`, `nix-tree`, `nix-output-monitor`).

## Consistency & Upstream Alignment
- **Identity Management**: 
    - All users and groups MUST have their `uid` and `gid` statically set to ensure consistency across different hardware and installations.
    - Assigned IDs MUST be unique across the entire fleet to prevent permission conflicts (e.g., during data migration or shared storage).
    - **ID Allocation Ranges**:
        - `100 - 499`: System-level users and groups managed by NixOS.
        - `1000 - 1999`: Primary human users (e.g., `nixos`).
        - `2000 - 2999`: Specialized development or administrative users.
        - `3000 - 4999`: OCI container / Self-hosted service users.
    - **Fleet ID Registry**: 
        - All static assignments MUST be registered below before implementation to prevent collisions.
        - **Registry Table**:
            | User/Group Name | UID | GID | Purpose | Allocation Range |
            | :--- | :--- | :--- | :--- | :--- |
            | `nixos` | 1000 | 1000 | Primary human user | Primary human users |
            | `apps` | 3000 | 3000 | Service user for self-hosted apps | Self-hosted service users |
    - Usernames MUST be consistently lowercase (e.g., `nixos`).
- **Networking Standard**: 
    - Use `NetworkManager` as the default networking manager for all hosts to ensure consistent WiFi handling and secret management integration.
    - WSL2 instances MUST use the shared `modules/common/wsl.nix` module which disables `systemd-resolved` and `networkd` to ensure compatibility with WSL's own networking stack.
- **Git Identity Policy**: Do not set global `user.name` or `user.email` in Home Manager configurations; identity should be managed on a per-project basis using local Git configs.
- **Community Standards**: Follow established Nix community patterns and best practices. Prioritize "the Nix way" over custom abstractions unless necessary.
- **Upstream Alignment**: Where possible, contribute improvements back to upstream projects (e.g., nixpkgs, home-manager) rather than maintaining local forks or complex overrides.
- **Naming Conventions**: Use descriptive, snake_case names for options and module files, adhering to common nixpkgs conventions.

## Gemini CLI Global Instructions

Gemini CLI instructions and expert personas are managed via a centralized `gemini.md` file deployed globally to `~/.gemini/gemini.md` via Home Manager. This ensures a consistent, distilled, and always-available set of directives across all hosts in the fleet.

### Guidelines for Instructions Deployment
- **Centralization**: All core directives, system-native workflows (e.g., `nh`, flakes), and expertise sections (e.g., Python) MUST reside in `home/config/AGENTS.md`.
- **Home Manager Integration**: The file MUST be symlinked to `~/.gemini/gemini.md` using the `home.file` option in `home/nixos.nix`.
- **Expertise Distillation**: Prefer concise, high-signal "Expertise Sections" within the global file over maintaining numerous individual skill files, unless a skill requires complex assets or scripts.
- **Autonomous Verification**: Instructions MUST emphasize autonomous execution of verification steps. Agents should attempt all verification themselves using available tools (SSH, `lsblk`, `nix-store`, etc.) and only ask the user to run things if they cannot accomplish the verification autonomously.

### Rationale
This model prioritizes visibility, simplicity, and cross-host consistency while reducing the overhead of managing individual ZIP-packaged skills for text-based directives.
