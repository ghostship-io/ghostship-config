## ADDED Requirements

### Requirement: Muximux SHALL expose the requested Ghostship service layout
The generated Muximux configuration SHALL place Grimmory and PriceBuddy on the main bar, SHALL place PriceBuddy immediately after Grimmory, and SHALL omit Honcho from the Muximux service list.

#### Scenario: Generated config places PriceBuddy after Grimmory
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the PriceBuddy entry appears after the Grimmory entry in the emitted service order
- **AND** the PriceBuddy entry is marked for the main bar rather than the dropdown

#### Scenario: Generated config no longer includes Honcho
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** no Honcho Muximux service entry is emitted

### Requirement: Homepage SHALL retain the existing Honcho entry
This change SHALL NOT remove or disable the existing Homepage Honcho service entry.

#### Scenario: Homepage keeps Honcho while Muximux removes it
- **WHEN** the updated host configuration is generated
- **THEN** Homepage still includes the Honcho service entry
- **AND** Muximux does not include the Honcho service entry
