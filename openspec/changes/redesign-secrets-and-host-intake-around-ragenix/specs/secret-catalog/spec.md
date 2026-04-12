## ADDED Requirements

### Requirement: Secret catalog defines logical-unit encrypted files
The repo SHALL declare encrypted secrets as logical units in `secrets/catalog.nix` instead of a single repo-wide encrypted YAML file. Each catalog entry SHALL define the backing encrypted file, recipient selection, ownership, mode, format, and exported fields for that logical unit.

#### Scenario: Catalog entry declares a service secret unit
- **WHEN** a service-level secret unit is added to the repo
- **THEN** the repo SHALL define that unit in `secrets/catalog.nix` with its encrypted `.age` file path, recipient selection, ownership, mode, format, and exported fields

### Requirement: Recipient policy uses SSH host ed25519 keys and reusable groups
The repo SHALL declare machine recipients from SSH host `ed25519` public keys in `secrets/recipients.nix` and SHALL compose reusable recipient groups from those host keys and any declared operator keys.

#### Scenario: New host is added to recipient policy
- **WHEN** a new host is integrated into the repo
- **THEN** the repo SHALL add that host's SSH `ed25519` public key to `secrets/recipients.nix`
- **AND** the repo SHALL compose any required recipient group membership from that declared key instead of repeating the raw key in each secret definition

### Requirement: Logical-unit secrets remain practical to edit and review
The repo SHALL store encrypted secrets by logical unit, usually one file per service or subsystem, and SHALL not require one encrypted file per scalar value as the default layout.

#### Scenario: Related service values are edited together
- **WHEN** an operator needs to change several related secret values for one service
- **THEN** the repo SHALL allow those values to live in the same logical-unit encrypted file
- **AND** the repo SHALL not require editing a separate encrypted file for each scalar value unless a concrete split is needed
