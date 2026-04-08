## ADDED Requirements

### Requirement: Chaptarr SHALL run as a persisted arr-style service on chill-penguin
The `chill-penguin` stack SHALL provide a self-hosted `chaptarr` service with persistent host-backed configuration so container replacement and host reactivation do not discard runtime state, generated API credentials, or application settings.

#### Scenario: Host configuration defines persisted Chaptarr state
- **WHEN** the `chill-penguin` host configuration is generated from the repo-managed modules
- **THEN** it includes a `chaptarr` container definition on `ghostship_net`
- **AND** it mounts a persistent host path for Chaptarr configuration data
- **AND** it configures Chaptarr with repo-managed runtime defaults rather than relying only on first-boot upstream behavior

### Requirement: Chaptarr SHALL use the shared Ghostship downloads root
Chaptarr SHALL mount the same shared downloads root used by the other arr services so it can process both torrent and usenet acquisitions without a divergent path contract.

#### Scenario: Chaptarr sees torrent and usenet downloads through the shared root
- **WHEN** the Chaptarr container is configured from the repo-managed host modules
- **THEN** it mounts `/mnt/share/Downloads` at `/downloads`
- **AND** that mount exposes both the `Torrent` and `Usenet` download trees to the service

### Requirement: Chaptarr and Grimmory SHALL share the books and audiobooks library roots
The stack SHALL mount the books and audiobooks library roots into Chaptarr and Grimmory so Chaptarr can manage both media types while Grimmory remains the primary consumption surface for them.

#### Scenario: Chaptarr receives separate books and audiobooks library mounts
- **WHEN** the Chaptarr container definition is generated
- **THEN** it mounts `/mnt/share/Library/Books` as a book library root
- **AND** it mounts `/mnt/share/Library/Audiobooks` as an audiobook library root

#### Scenario: Grimmory receives matching shared library mounts
- **WHEN** the Grimmory container definition is generated after this change
- **THEN** it mounts `/mnt/share/Library/Books` for book consumption
- **AND** it mounts `/mnt/share/Library/Audiobooks` for audiobook consumption

### Requirement: Chaptarr SHALL use operator-supplied secret stubs for sensitive runtime values
The repo SHALL provide plaintext Chaptarr secret scaffolding in `secrets.dec.yaml` and a corresponding secret bundle reference in the host configuration so operators can supply sensitive runtime values such as the API key without hardcoding them into the Nix module.

#### Scenario: Repo-managed secret scaffolding exists for Chaptarr
- **WHEN** the repo is prepared for Chaptarr rollout
- **THEN** `secrets.dec.yaml` contains Chaptarr secret stub entries for required operator-supplied values
- **AND** the host configuration declares a `chaptarr-secrets` secret input for the service

### Requirement: Chaptarr SHALL remain visible in the Ghostship dashboards
Homepage and Muximux SHALL expose Chaptarr as part of the self-hosted stack so operators can discover and launch the service from the existing dashboard surfaces.

#### Scenario: Homepage includes Chaptarr in automation services
- **WHEN** Homepage `services.yaml` is generated from the repo-managed module
- **THEN** the `Automation` group contains a Chaptarr entry
- **AND** that entry is associated with the managed `chaptarr` container on `chill-penguin`

#### Scenario: Muximux includes Chaptarr with the arr stack
- **WHEN** the Muximux service configuration is generated from the repo-managed module
- **THEN** it emits a Chaptarr entry in the dropdown service list
- **AND** that entry is grouped with the arr-style services rather than the general utility tools
