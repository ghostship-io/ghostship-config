## ADDED Requirements

### Requirement: PriceBuddy generated runtime env SHALL declare the canonical public HTTPS origin
The generated PriceBuddy app env SHALL include explicit `APP_URL` and
`ASSET_URL` values for `https://pricebuddy.ghostship.io` so Laravel and
Filament generate public app and asset URLs on the same HTTPS origin.

#### Scenario: Generated env includes public origin settings
- **WHEN** Ghostship generates `/srv/apps/pricebuddy/pricebuddy.env` for
  `chill-penguin`
- **THEN** the file contains
  `APP_URL=https://pricebuddy.ghostship.io`
- **AND** the file contains
  `ASSET_URL=https://pricebuddy.ghostship.io`

### Requirement: PriceBuddy runtime verification SHALL reject mixed-content public URL generation
Ghostship verification for PriceBuddy SHALL confirm that the running
application resolves its effective app and asset URLs to
`https://pricebuddy.ghostship.io` rather than `http://localhost` or `http://`
public-origin variants that would trigger browser mixed-content failures.

#### Scenario: Verification confirms effective HTTPS app and asset URLs
- **WHEN** operators verify a deployed PriceBuddy update on `chill-penguin`
- **THEN** the running container reports `config('app.url')` as
  `https://pricebuddy.ghostship.io`
- **AND** the running container resolves asset URLs under
  `https://pricebuddy.ghostship.io/...`
