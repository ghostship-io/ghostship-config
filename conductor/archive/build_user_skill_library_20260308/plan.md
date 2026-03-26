# Implementation Plan: Build User Skill Library

## Phase 1: Declarative Skill Infrastructure
- [x] Task: Define the skill directory structure in `home/nixos.nix` using `home.file`. 16dc220
- [x] Task: Add logic to `home/nixos.nix` to manage `~/.gemini/skills/` declaratively. f2faec2
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Declarative Skill Infrastructure' (Protocol in workflow.md)

## Phase 2: NixOS Expert Skill Migration (Declarative)
- [x] Task: Add `nixos-expert` skill definition to `home/nixos.nix`. f2faec2
- [x] Task: Use `builtins.readFile` to import `nixos.md` content into the skill's `SKILL.md`. f2faec2
- [x] Task: Define the `metadata.json` for `nixos-expert` in `home/nixos.nix`. 0d44563
- [ ] Task: Conductor - User Manual Verification 'Phase 2: NixOS Expert Skill Migration' (Protocol in workflow.md)

## Phase 3: Iterative Skill Integration
- [x] Task: Prompt the user for additional MD files to integrate. e9cca60
- [x] Task: For each provided file:
    - [x] Task: Prompt for skill metadata (name, description, tags). e9cca60
    - [x] Task: Add the skill definition to `home/nixos.nix`. e9cca60
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Iterative Skill Integration' (Protocol in workflow.md)
