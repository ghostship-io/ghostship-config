## ADDED Requirements

### Requirement: Bootstrap capture writes a temporary intake bundle
The repo SHALL provide a bootstrap capture workflow that writes host onboarding artifacts as files in a temporary intake bundle instead of printing one pasted JSON payload for repo-side registration.

#### Scenario: New host capture runs successfully
- **WHEN** the bootstrap capture workflow runs for a host
- **THEN** it SHALL write a temporary intake bundle containing host metadata, a standalone `hardware-configuration.nix`, and the host SSH `ed25519` public key

### Requirement: Codex-assisted integration uses the temporary intake directory
The supported host onboarding workflow SHALL copy the intake bundle into `references/host-intake/<hostname>/` and use Codex to integrate that host into the repo from those files.

#### Scenario: Operator stages host intake for Codex
- **WHEN** an operator wants Codex to integrate a new host
- **THEN** the operator SHALL be able to copy the intake bundle into `references/host-intake/<hostname>/`
- **AND** Codex SHALL have the required file artifacts there to integrate the host into `hosts/<hostname>/`, `flake.nix`, and recipient policy

### Requirement: Temporary intake directories are removed after integration
The repo SHALL treat `references/host-intake/<hostname>/` as temporary working state rather than permanent archived source material.

#### Scenario: Host integration completes
- **WHEN** Codex finishes integrating a staged host intake bundle
- **THEN** the workflow SHALL remove the temporary `references/host-intake/<hostname>/` directory
- **AND** the repo SHALL not require keeping that intake directory as permanent tracked state
