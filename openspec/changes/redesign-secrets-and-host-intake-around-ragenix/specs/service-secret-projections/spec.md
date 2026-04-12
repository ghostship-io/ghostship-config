## ADDED Requirements

### Requirement: Services consume projected secret surfaces
The repo SHALL provide a projection layer that renders consumer-specific secret surfaces from catalog-defined logical units instead of requiring each service module to wire raw secret file paths and source whole bundles ad hoc.

#### Scenario: Service needs a runtime env file
- **WHEN** a service requires secret values at runtime
- **THEN** the repo SHALL render a service-specific secret surface from catalog-defined logical units
- **AND** the service module SHALL consume that projected surface instead of open-coding repeated raw secret file path lookups

### Requirement: Shared secret fields can be projected to multiple consumers
The repo SHALL allow one logical secret unit to export fields that can be projected into multiple consumers when those consumers need shared data.

#### Scenario: Two services share one secret field
- **WHEN** multiple services need the same secret field from one logical unit
- **THEN** the repo SHALL project that field to each consumer from the same catalog-defined source
- **AND** the repo SHALL not require duplicating the underlying secret value across multiple encrypted files solely to satisfy those consumers

### Requirement: Consumers receive only the fields they need
Projected secret surfaces SHALL include only the exported fields requested by the consumer rather than every value from every referenced logical unit.

#### Scenario: Homepage uses several service credentials
- **WHEN** Homepage or another aggregator consumes shared secret data from multiple logical units
- **THEN** the repo SHALL project only the exported fields that aggregator declares
- **AND** the resulting runtime surface SHALL omit unrelated fields from the source logical units
