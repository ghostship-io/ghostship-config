## ADDED Requirements

### Requirement: Hermes SHALL expose a persistent workspace outside HERMES_HOME
The self-hosted Hermes service SHALL expose a direct persistent workspace at
`/home/hermes/workspace` backed by `/srv/apps/hermes/workspace` on
`chill-penguin`.

#### Scenario: Hermes workspace bind mount is generated
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** `/srv/apps/hermes/workspace` SHALL be mounted at
  `/home/hermes/workspace`
- **AND** `/srv/apps/hermes/workspace` SHALL be managed as a durable host
  directory under `/srv/apps`
- **AND** the existing Hermes home mount at `/home/hermes/.hermes` SHALL remain
  in place
