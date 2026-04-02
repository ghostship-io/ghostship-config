# muximux-service-placement Specification

## Purpose
TBD - created by archiving change fix-pricebuddy-and-muximux. Update Purpose after archive.
## Requirements
### Requirement: Muximux SHALL expose the requested Ghostship service layout
The generated Muximux configuration SHALL keep PriceBuddy in the dropdown, SHALL place PriceBuddy immediately after Bazarr, and SHALL omit Honcho from the Muximux service list.

#### Scenario: Generated config places PriceBuddy after Bazarr in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the PriceBuddy entry appears after the Bazarr entry in the emitted service order
- **AND** the PriceBuddy entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config no longer includes Honcho
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** no Honcho Muximux service entry is emitted

### Requirement: Homepage SHALL omit Honcho after stack retirement
Once Honcho is retired from the Ghostship stack, Homepage SHALL omit the Honcho service and infrastructure entries.

#### Scenario: Homepage removes Honcho while Muximux also omits it
- **WHEN** the updated host configuration is generated
- **THEN** Homepage does not include the Honcho service entry
- **AND** Muximux does not include the Honcho service entry
