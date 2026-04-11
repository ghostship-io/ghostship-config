## Context

Hermes on `chill-penguin` runs from the repo-managed
[`modules/self-hosted/hermes.nix`](/home/nixos/nixos-config/modules/self-hosted/hermes.nix)
container definition and already injects Discord channel IDs and allowlists
through environment variables. The upstream `ghostship-hermes` image also
supports Discord gateway behavior flags, including `DISCORD_REQUIRE_MENTION`,
`DISCORD_FREE_RESPONSE_CHANNELS`, and `DISCORD_AUTO_THREAD`, but the repo does
not currently set them.

The desired policy is channel-scoped rather than profile-scoped:

- the general channel remains mention-only
- the dedicated assistant, operations, and supervisor channels can respond
  without mention
- Hermes never auto-creates Discord threads and instead replies directly in the
  current channel

Because Hermes reads these flags at container startup, any change requires a
Hermes container restart during deploy.

## Goals / Non-Goals

**Goals:**
- Express Hermes Discord reply policy declaratively in repo-managed Nix config.
- Keep mention-gating enabled by default while allowing channel-specific
  free-response exceptions.
- Disable Discord auto-thread creation without patching the upstream image.
- Preserve a clear deployment and rollback path for `chill-penguin`.

**Non-Goals:**
- Changing Discord bot tokens, allowed-user lists, or persona-channel mapping.
- Introducing per-profile Discord routing logic beyond the current channel ID
  wiring.
- Modifying Hermes application code inside the image.

## Decisions

### Set Discord gateway behavior through Hermes container environment variables

The repo will set the upstream-supported environment variables directly in the
Hermes container definition:

- `DISCORD_REQUIRE_MENTION=true`
- `DISCORD_AUTO_THREAD=false`
- `DISCORD_FREE_RESPONSE_CHANNELS=<assistant,operations,supervisor ids>`

This keeps the repo aligned with the upstream image contract and avoids
maintaining a separate runtime config file inside the persistent Hermes home.

Alternative considered:
- Writing `discord.auto_thread` and related settings into Hermes config under
  `/home/hermes`.
  Rejected because env vars already have first-class upstream support, fit the
  existing container-managed secret/config pattern, and are simpler to audit in
  Nix.

### Keep general-channel behavior implicit via default mention requirement

The general channel will remain mention-only by leaving it out of
`DISCORD_FREE_RESPONSE_CHANNELS` while keeping `DISCORD_REQUIRE_MENTION=true`.
This avoids duplicating a separate allow/deny list for the default case.

Alternative considered:
- Adding an explicit general-channel-only env var or custom logic.
  Rejected because the upstream routing model already treats free-response
  channels as exceptions to the default mention requirement.

### Treat Hermes restart as part of the deploy contract

The change should document and verify that a Hermes container restart is needed
 after activation so the updated Discord gateway env vars are loaded.

Alternative considered:
- Relying on a passive future restart or auto-update cycle.
  Rejected because the behavior change is user-facing and should become active
  at deployment time.

## Risks / Trade-offs

- Free-response channels may generate more bot replies than mention-only
  channels → limit `DISCORD_FREE_RESPONSE_CHANNELS` to the dedicated assistant,
  operations, and supervisor channels.
- Operators may assume a NixOS switch alone is sufficient → document that
  Hermes must restart or be redeployed for the new env vars to take effect.
- Upstream Hermes Discord config names could change in a future image release
  → rely on the currently verified upstream env variables and re-verify during
  future image upgrades if Discord behavior changes unexpectedly.
