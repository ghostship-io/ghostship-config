## ADDED Requirements

### Requirement: Default repo dev shell exports environment successfully
The repo SHALL provide a default flake dev shell that exports successfully through supported develop-host entrypoints instead of failing inside Nix environment export.

#### Scenario: `nix print-dev-env` succeeds for default shell
- **WHEN** `nix print-dev-env -L .#default` runs from repo root on supported develop-host workflow
- **THEN** it SHALL produce environment output without `get-env.sh failed to produce an environment`

#### Scenario: `nix develop` succeeds for default shell
- **WHEN** `nix develop .#default --command bash -lc 'printf ok'` runs from repo root
- **THEN** command SHALL enter repo default dev shell and exit successfully

#### Scenario: `direnv` no longer falls back to stale shell state
- **WHEN** `direnv` loads repo `.envrc` after this change
- **THEN** it SHALL load current default flake shell without reporting that current dev shell evaluation failed and previous environment was reused

### Requirement: Repo-managed dev-shell tooling stays explicit
The repo SHALL keep required develop-host shell tooling available through repo-managed configuration rather than depending on undocumented ad-hoc host installs.

#### Scenario: Default shell declares supported tooling surface
- **WHEN** repo default dev shell definition is inspected
- **THEN** it SHALL declare or intentionally replace tools needed for repo flake, secret, and formatting workflow through repo-managed configuration

#### Scenario: Tooling changes are documented when shell composition changes
- **WHEN** a tool is removed from default shell to avoid failing export behavior
- **THEN** active workflow documentation SHALL identify replacement access path or revised supported workflow

### Requirement: Active docs describe shell activation expectations
The repo SHALL document how develop-host users pick up repaired default shell behavior and any remaining caveats tied to current Nix behavior.

#### Scenario: Docs describe refresh step
- **WHEN** active workflow documentation is inspected after this change
- **THEN** it SHALL describe any required `direnv reload`, new shell, or rebuild step needed to observe repaired default shell behavior

#### Scenario: Docs describe residual upstream limitation
- **WHEN** active workflow documentation is inspected after this change
- **THEN** it SHALL call out any remaining upstream Nix-specific caveat if final mitigation depends on a known exporter limitation
