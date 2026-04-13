## ADDED Requirements

### Requirement: Hermes SHALL project BookStack service access through the managed utility env contract
The managed Hermes container on `chill-penguin` SHALL expose the BookStack service URL and token pair through the same repo-managed utility env contract used for the rest of the bundled utilities.

#### Scenario: BookStack URL is present on the Hermes container
- **WHEN** the Hermes container definition is evaluated for `chill-penguin`
- **THEN** it SHALL set `BOOKSTACK_URL`
- **AND** `BOOKSTACK_URL` SHALL point at `https://bookstack.ghostship.io`

#### Scenario: BookStack token pair is projected from the service-local secret bundle
- **WHEN** the Hermes runtime env is generated
- **THEN** repo-managed wiring SHALL read `BOOKSTACK_TOKEN_ID` and `BOOKSTACK_TOKEN_SECRET` from `bookstack-secrets`
- **AND** it SHALL write those values into the generated Hermes runtime env file
- **AND** it SHALL not require a second Hermes-only BookStack credential bundle
