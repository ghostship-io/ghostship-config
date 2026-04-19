## ADDED Requirements

### Requirement: WSL provides explicit repo-managed npm and npx FHS wrappers
WSL host configuration SHALL provide explicit `npm` and `npx` compatibility entrypoints for FHS paths instead of exposing raw upstream launcher shims that depend on the original npm filesystem layout.

#### Scenario: npm compatibility entrypoint is explicit
- **WHEN** the supported WSL `/usr/bin/npm` path is inspected
- **THEN** it SHALL resolve through a repo-managed wrapper entrypoint that execs the real Nix store `npm` binary

#### Scenario: npx compatibility entrypoint is explicit
- **WHEN** the supported WSL `/usr/bin/npx` path is inspected
- **THEN** it SHALL resolve through a repo-managed wrapper entrypoint that execs the real Nix store `npx` binary

### Requirement: WSL npm and npx FHS wrappers avoid the broken raw shim behavior
The supported WSL `npm` and `npx` FHS paths SHALL not depend on raw launcher files whose relative module lookup fails under `/usr/bin`.

#### Scenario: npm wrapper does not use the raw upstream shim path directly
- **WHEN** the repo-managed WSL `npm` compatibility path is reviewed
- **THEN** it SHALL not depend on the broken raw launcher behavior that resolves `../lib/cli.js` relative to `/usr/bin`

#### Scenario: npx wrapper does not use the raw upstream shim path directly
- **WHEN** the repo-managed WSL `npx` compatibility path is reviewed
- **THEN** it SHALL not depend on the broken raw launcher behavior that resolves `../lib/cli.js` relative to `/usr/bin`

### Requirement: Docs describe the supported Node package-manager compatibility path
The repo SHALL document that the supported WSL `npm` and `npx` compatibility paths are explicit repo-managed wrappers rather than accidental raw upstream shims.

#### Scenario: WSL workflow docs mention wrapper-backed compatibility
- **WHEN** the WSL workflow documentation or repo agent memory is inspected
- **THEN** it SHALL describe `/usr/bin/npm` and `/usr/bin/npx` as explicit compatibility wrappers
