# Specification: Build User Skill Library

## Overview
Create a standardized library of Gemini skills in the user's home directory (`~/.gemini/skills/`) to extend Gemini's expert capabilities. The initial build-out will include a "NixOS Expert" skill based on the local `nixos.md` file, followed by additional skills integrated from user-provided Markdown files.

## Functional Requirements
- **Skill Directory Initialization**:
    - Ensure the `~/.gemini/skills/` directory exists and is correctly configured.
- **NixOS Expert Skill Integration**:
    - Convert the root `nixos.md` file into a full skill directory named `nixos-expert`.
- **Manual Skill Conversion**:
    - Integrate additional user-provided `.md` files into the library.
    - For each skill, the user will be prompted for its name, description, and tags.
- **Skill Structure**:
    - Each skill must follow the **Standardized (Full)** structure:
        - `SKILL.md`: Contains the expert instructions and role definitions.
        - `metadata.json`: Contains the name, description, and tags.
- **Conflict Handling**:
    - Overwrite any existing skill with the same name during the build-out.

## Non-Functional Requirements
- **Consistency**: All skills must adhere to the same naming and structure conventions.
- **Accessibility**: Skills must be placed in a location where the Gemini CLI can discover and activate them.

## Acceptance Criteria
1. The `~/.gemini/skills/` directory is present and contains the `nixos-expert` skill.
2. The `nixos-expert` skill includes a `SKILL.md` with content from `nixos.md` and a correctly populated `metadata.json`.
3. Subsequent skills from provided MD files are successfully integrated with prompted metadata.
4. Overwriting logic works correctly for duplicate skill names.

## Out of Scope
- Automated conversion scripts (all conversions are manual).
- Advanced tool or plugin management beyond the `SKILL.md` instructions.
- Remote repository synchronization.
