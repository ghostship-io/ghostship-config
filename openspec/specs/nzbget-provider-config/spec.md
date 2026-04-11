# nzbget-provider-config Specification

## Purpose
Define the managed NZBGet provider set and the required cleanup when a retired provider is removed from desired and live state.
## Requirements
### Requirement: Managed NZBGet provider set excludes retired providers
The repo SHALL define only active NZBGet upstream providers in managed configuration. When a provider is retired, the tracked NZBGet module and the local plaintext secret mirror used for follow-up re-encryption SHALL remove that provider's server block and credentials instead of preserving a disabled placeholder.

#### Scenario: Repo-managed config keeps only active providers
- **WHEN** the repo generates NZBGet configuration for `chill-penguin`
- **THEN** `modules/self-hosted/nzbget.nix` defines the active Eweka `Server1` settings
- **AND** the managed configuration does not define a `Server2` entry for `eu.usenetprime.com`
- **AND** `modules/self-hosted/nzbget.nix` does not reference `NZBGET_SERVER2_USER` or `NZBGET_SERVER2_PASS`
- **AND** the local `secrets.dec.yaml` plaintext mirror does not contain `NZBGET_SERVER2_USER` or `NZBGET_SERVER2_PASS`

### Requirement: Live NZBGet state is reconciled after provider retirement
When a retired provider is removed from desired state, the applied host state SHALL be cleaned so the running NZBGet service no longer references that provider.

#### Scenario: Host cleanup removes UsenetPrime references
- **WHEN** the UsenetPrime provider retirement is applied to `chill-penguin`
- **THEN** `/srv/apps/nzbget/nzbget.conf` does not contain `Server2.*` entries for `eu.usenetprime.com`
- **AND** the running `podman-nzbget.service` starts successfully after the cleanup
- **AND** live verification no longer finds `usenetprime` in the active NZBGet config

