## MODIFIED Requirements

### Requirement: Muximux SHALL expose the requested Ghostship service layout
The generated Muximux configuration SHALL keep PriceBuddy in the dropdown, SHALL place Chaptarr in the dropdown immediately before Bazarr, SHALL place BookStack immediately after Prowlarr, SHALL place Changedetection immediately after RSS-Bridge, and SHALL omit Honcho from the Muximux service list.

#### Scenario: Generated config places PriceBuddy after Bazarr in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the PriceBuddy entry appears after the Bazarr entry in the emitted service order
- **AND** the PriceBuddy entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config places Chaptarr before Bazarr in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the Chaptarr entry appears before the Bazarr entry in the emitted service order
- **AND** the Chaptarr entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config places BookStack after Prowlarr
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the BookStack entry appears after the Prowlarr entry in the emitted service order
- **AND** the BookStack entry is enabled in the generated service list

#### Scenario: Generated config places Changedetection after RSS-Bridge in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the Changedetection entry appears after the RSS-Bridge entry in the emitted service order
- **AND** the Changedetection entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config no longer includes Honcho
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** no Honcho Muximux service entry is emitted
