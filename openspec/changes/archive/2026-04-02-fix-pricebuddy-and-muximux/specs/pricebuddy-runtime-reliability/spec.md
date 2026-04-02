## ADDED Requirements

### Requirement: PriceBuddy token sync SHALL preserve a valid bearer token format across restarts
The generated PriceBuddy agent token file SHALL persist a bearer value in `<token-id>|<raw-token>` form, and repeated token-sync runs SHALL preserve exactly one token ID prefix rather than compounding prefixes from prior runs.

#### Scenario: First successful token sync writes a valid bearer token
- **WHEN** the PriceBuddy token-sync step creates or updates the `ghostship-agent` personal access token
- **THEN** the persisted `PRICEBUDDY_API_TOKEN` value is written as exactly one `<token-id>|<raw-token>` pair

#### Scenario: Repeated token sync does not duplicate token IDs
- **WHEN** the PriceBuddy token-sync step runs again with an existing persisted bearer token
- **THEN** it extracts the raw token portion before hashing or rewriting the file
- **AND** the rewritten `PRICEBUDDY_API_TOKEN` value still contains exactly one token ID prefix

### Requirement: PriceBuddy deployment verification SHALL distinguish Ghostship runtime failures from upstream application issues
Ghostship verification for PriceBuddy SHALL confirm the generated env files, app container, database, scraper connectivity, and final token format, and SHALL record remaining upstream or third-party failures separately from deployment misconfiguration.

#### Scenario: Verification confirms Ghostship runtime wiring
- **WHEN** operators verify a deployed PriceBuddy update on `chill-penguin`
- **THEN** they can confirm the generated env files exist with the expected service endpoints
- **AND** the app container can reach the scraper sidecar
- **AND** the persisted agent token format is valid after restart

#### Scenario: Verification records residual non-environment failures
- **WHEN** PriceBuddy still reports application-level auth issues or target-site anti-bot failures after the runtime checks pass
- **THEN** those failures are documented as residual upstream or target-site issues rather than Ghostship environment regressions
