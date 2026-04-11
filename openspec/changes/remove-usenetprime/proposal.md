## Why

`chill-penguin` still carries a second NZBGet server definition for `eu.usenetprime.com` even though that provider is no longer used. The repo-managed activation script, decrypted secrets, and live host state all still preserve those credentials, and the host log shows repeated authorization failures against the retired server.

## What Changes

- Remove the managed `Server2` / `eu.usenetprime.com` configuration from the NZBGet activation script in `modules/self-hosted/nzbget.nix`.
- Remove the retired `NZBGET_SERVER2_*` credentials from `secrets.dec.yaml` so the desired secret bundle only contains the active provider.
- Manually clean the live `chill-penguin` NZBGet state so `/srv/apps/nzbget/nzbget.conf` no longer contains the retired server and the running service is restarted against the cleaned config.
- Update active change tracking and release notes for the provider retirement.

## Capabilities

### New Capabilities
- `nzbget-provider-config`: Defines the managed NZBGet provider set and the required secret/config cleanup when a provider is retired.

### Modified Capabilities
- None.

## Impact

- Affected code: `modules/self-hosted/nzbget.nix`, `secrets.dec.yaml`, and `CHANGELOG.md`.
- Affected systems: the `chill-penguin` self-hosted stack and its live `/srv/apps/nzbget` state.
- Activation/manual cleanup: the repo change removes the retired provider from desired state, and this apply will also manually clean the current host config and restart NZBGet so the live service matches immediately.
