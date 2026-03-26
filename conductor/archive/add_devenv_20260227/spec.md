# Specification: Add 'devenv' to Packages

## Overview
Install `devenv` into the user-level package configuration via Home Manager. This tool is a declarative development environment manager that simplifies setting up reproducible developer shells.

## Functional Requirements
- **Home Manager Integration**: Add `devenv` to the list of user packages in `home/nixos.nix` (or appropriate home configuration).
- **Multi-host Support**: Ensure `devenv` is available on all hosts (currently `launch-octopus` and any future hosts).
- **Binary Cache (Cachix)**: Configure `devenv.cachix.org` as a binary substituter to speed up environment builds.
- **Direnv Integration**: Ensure `direnv` and `nix-direnv` are configured to work seamlessly with `devenv`.
- **Tooling**: Ensure the `devenv` CLI is accessible from the Fish shell.

## Non-Functional Requirements
- **Reproducibility**: Use Nix Flakes to lock the `devenv` version.
- **Cleanliness**: Maintain the existing modular structure of the configuration.

## Acceptance Criteria
- [ ] `devenv` command is available in the shell.
- [ ] `devenv init` works in a new project directory.
- [ ] Configuration is applied across all hosts via common home manager modules.
- [ ] `devenv.cachix.org` is present in `/etc/nix/nix.conf` as a substituter.

## Out of Scope
- Configuring complex per-project `devenv` environments.
