## Why

`chill-penguin` still carries a second NZBGet server definition for `eu.usenetprime.com` even though that provider is no longer used. The repo-managed activation script, decrypted secrets, and live host state all still preserve those credentials, and the host log shows repeated authorization failures against the retired server.

## What Changes

- Remove the managed `Server2` / `eu.usenetprime.com` configuration from the NZBGet activation script in `modules/self-hosted/nzbget.nix`.
- Remove the retired `NZBGET_SERVER2_*` credentials from the local `secrets.dec.yaml` plaintext mirror so the follow-up re-encryption step can retire them from `secrets.yaml`.
- Manually clean the live `chill-penguin` NZBGet state so `/srv/apps/nzbget/nzbget.conf` no longer contains the retired server and the running service is restarted against the cleaned config.
- Update active change tracking and release notes for the provider retirement.

## Capabilities

### New Capabilities
- `nzbget-provider-config`: Defines the managed NZBGet provider set and the required secret/config cleanup when a provider is retired.

### Modified Capabilities
- None.

## Impact

- Affected code: `modules/self-hosted/nzbget.nix`, the local `secrets.dec.yaml` plaintext mirror, and `CHANGELOG.md`.
- Affected systems: the `chill-penguin` self-hosted stack and its live `/srv/apps/nzbget` state.
- Activation/manual cleanup: this apply removes the retired provider from tracked NZBGet config, cleans the local plaintext secret mirror, and manually cleans the current host config. Re-encrypting `secrets.yaml` remains a follow-up step the user will perform separately.
