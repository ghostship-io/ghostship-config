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

### Requirement: WSL2 bootstrap ensures the SSH host ed25519 key exists
The bootstrap capture workflow SHALL ensure that WSL2 hosts have an SSH host `ed25519` key before writing the intake bundle because those hosts may not generate that key by default.

#### Scenario: WSL2 host is missing its host ed25519 key
- **WHEN** bootstrap capture runs on a WSL2 host without `ssh_host_ed25519_key.pub`
- **THEN** the workflow SHALL generate the SSH host keys before continuing
- **AND** it SHALL fail loudly if the `ssh_host_ed25519_key.pub` file still does not exist after that generation step
