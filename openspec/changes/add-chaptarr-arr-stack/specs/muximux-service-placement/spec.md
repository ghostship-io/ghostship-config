## MODIFIED Requirements

### Requirement: Muximux SHALL expose the requested Ghostship service layout
The generated Muximux configuration SHALL keep Chaptarr in the dropdown with the arr stack, SHALL place Chaptarr after Bazarr and before `n8n`, SHALL keep PriceBuddy in the dropdown after `n8n`, SHALL place Changedetection immediately after RSS-Bridge, and SHALL omit Honcho from the Muximux service list.

#### Scenario: Generated config places Chaptarr after Bazarr in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the Chaptarr entry appears after the Bazarr entry in the emitted service order
- **AND** the Chaptarr entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config places n8n after Chaptarr in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the `n8n` entry appears after the Chaptarr entry in the emitted service order
- **AND** the `n8n` entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config keeps PriceBuddy in the dropdown after n8n
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the PriceBuddy entry appears after the `n8n` entry in the emitted service order
- **AND** the PriceBuddy entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config places Changedetection after RSS-Bridge in the dropdown
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** the Changedetection entry appears after the RSS-Bridge entry in the emitted service order
- **AND** the Changedetection entry is marked for the dropdown rather than the main bar

#### Scenario: Generated config no longer includes Honcho
- **WHEN** the Muximux configuration is generated from the repo-managed module
- **THEN** no Honcho Muximux service entry is emitted
