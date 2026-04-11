## Why

Hermes currently auto-creates Discord threads when it is mentioned in server
channels, which pushes conversations out of the channel flow and does not match
the desired moderation model for Ghostship. The Discord gateway should keep
mention-gating on for the general channel, allow free-response behavior in the
dedicated assistant and operations channels, and reply directly in-channel
without creating threads.

## What Changes

- Add a repo-managed Hermes Discord routing capability that defines mention
  behavior and in-channel reply behavior for `chill-penguin`.
- Configure Hermes to disable Discord auto-thread creation by setting
  `DISCORD_AUTO_THREAD=false`.
- Configure Hermes to keep mention requirements enabled by default while
  populating `DISCORD_FREE_RESPONSE_CHANNELS` for the dedicated free-response
  channels.
- Preserve the existing general Discord channel as a mention-required channel.
- Document the host activation impact: the Hermes container must be restarted or
  redeployed for updated Discord gateway environment variables to take effect.

## Capabilities

### New Capabilities
- `hermes-discord-routing`: Define the repo-managed Discord mention policy,
  free-response channel exceptions, and no-auto-thread behavior for Hermes on
  `chill-penguin`.

### Modified Capabilities
- None.

## Impact

- Affected host: `chill-penguin` server host.
- Affected code: `modules/self-hosted/hermes.nix` and supporting docs.
- Affected runtime behavior: Hermes Discord gateway environment variables and
  channel reply behavior.
- Activation impact: requires a Hermes container restart during deploy so the
  new Discord gateway environment variables are applied.
