---
name: nix
description: Use for Nix flakes, NixOS modules, Home Manager, packaging, and native nix or nixos-rebuild workflows in this repo.
---

# nix

Use this skill for any repo work that changes flake wiring, NixOS modules,
Home Manager modules, package definitions, or host builds.

## Core workflow

- Prefer native `nix`, `nixos-rebuild`, and `switch-to-configuration`. Do not
  use `nh`.
- Build first. Do not switch or deploy unless the user explicitly asks for it.
- Keep host or admin defaults in NixOS modules and interactive user tooling in
  Home Manager.
- Use package references like `${pkgs.package}/bin/cmd` instead of hardcoded
  `/bin` paths.
- When behavior or workflow changes, update `README.md`, `CHANGELOG.md`, and
  `AGENTS.md`.

## Verification

- Only use a local `nix build .#nixosConfigurations.<host>.config.system.build.toplevel -L`
  when the target host architecture matches the current machine. If it does not
  match, use another validation path such as remote host builds, evaluation-only
  checks, or architecture-appropriate builders.
- If a command needs privileges, tell the user to run it from a root shell or a
  direct root SSH session.

## Read when needed

- [Command and deploy patterns](references/command-reference.md)
- [Flake patterns](references/flake-patterns.md)
- [Module patterns](references/module-patterns.md)
- [Packaging patterns](references/packaging.md)
