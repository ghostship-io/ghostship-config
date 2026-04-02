## ADDED Requirements

### Requirement: Dashboards SHALL omit Honcho after stack retirement
Once Honcho is retired from the Ghostship stack, both Muximux and Homepage SHALL omit Honcho entries.

#### Scenario: Homepage no longer includes Honcho
- **WHEN** the updated host configuration is generated after Honcho retirement
- **THEN** Homepage does not include a Honcho service tile
- **AND** Muximux does not include a Honcho service entry

## REMOVED Requirements

### Requirement: Homepage SHALL retain the existing Honcho entry
**Reason**: Honcho is being retired from the Ghostship stack instead of remaining as a supported Homepage-only service.
**Migration**: Remove the Honcho Homepage tile and rely on the retired-stack cleanup workflow instead of preserving dashboard access.
