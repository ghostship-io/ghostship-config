## Context

`modules/self-hosted/nzbget.nix` currently patches `/srv/apps/nzbget/nzbget.conf` with both the active Eweka server and a retired optional `Server2` pointing at `eu.usenetprime.com`. `secrets.dec.yaml` still carries `NZBGET_SERVER2_USER` and `NZBGET_SERVER2_PASS`, which flow into `/run/secrets/nzbget-secrets` on `chill-penguin`. The live host state confirms that persisted config and secrets still exist and that NZBGet has logged repeated `Access Denied` failures against UsenetPrime.

This change touches both declarative desired state and mutable live host state. The design needs to remove the retired provider cleanly without disturbing the remaining Eweka configuration or the rest of the self-hosted stack.

## Goals / Non-Goals

**Goals:**
- Remove the retired UsenetPrime server from repo-managed NZBGet configuration.
- Remove the retired provider credentials from the decrypted secret source.
- Clean the current `chill-penguin` NZBGet config so the running service stops referencing UsenetPrime immediately.
- Leave the active Eweka provider configuration intact.

**Non-Goals:**
- Reworking the NZBGet service, categories, or unrelated download tooling.
- Rotating the remaining Eweka credentials.
- Introducing a generalized multi-provider abstraction for NZBGet.
- Editing archived docs that only record historical planning context.

## Decisions

### Remove the provider entirely instead of merely disabling it
The repo should delete the `Server2.*` settings and the `NZBGET_SERVER2_*` secret inputs rather than leaving a disabled placeholder.

Why:
- The provider is explicitly unused.
- Leaving inert credentials in declarative config keeps unnecessary secret material around.
- NZBGet’s live logs show the retired server is still being exercised, so partial removal is not enough.

Alternatives considered:
- Set `Server2.Active=no`: rejected because it would still preserve dead config and credentials.
- Leave the repo alone and only edit the live host: rejected because the next activation would recreate the retired server.

### Apply the host cleanup directly on `chill-penguin`
The apply should manually remove the live `Server2.*` entries from `/srv/apps/nzbget/nzbget.conf`, restart `podman-nzbget.service`, and verify that no live config or generated secret file still references UsenetPrime.

Why:
- The user asked for removal from the server itself now, not only after a future host rebuild.
- The current host state is already divergent enough to keep generating authorization noise.

Alternatives considered:
- Wait for a later rebuild to reconcile live state: rejected because it leaves the current service misconfigured.
- Delete the entire NZBGet config and let the container regenerate it: rejected because the repo currently patches an existing config surgically and a broader reset is unnecessary.

## Risks / Trade-offs

- [Manual host edits diverge from the repo change] -> Apply the repo change in the same session and verify both the worktree diff and the host state after restart.
- [Removing the wrong NZBGet lines corrupts the config] -> Target only the `Server2.*` block and confirm `Server1.*` remains present afterward.
- [Future activation still expects `NZBGET_SERVER2_*`] -> Remove every repo reference to those env vars before validating the change.

## Migration Plan

1. Delete the retired `Server2.*` wiring from `modules/self-hosted/nzbget.nix`.
2. Remove `NZBGET_SERVER2_USER` and `NZBGET_SERVER2_PASS` from `secrets.dec.yaml`.
3. Update the changelog entry for the retirement.
4. Validate the `chill-penguin` config still evaluates from the worktree.
5. Manually remove `Server2.*` from `/srv/apps/nzbget/nzbget.conf` on `chill-penguin`, restart `podman-nzbget.service`, and verify no remaining live references to `usenetprime` or `NZBGET_SERVER2` remain.

Rollback would restore the deleted repo lines and re-add the live `Server2.*` block if the backup provider is needed again.

## Open Questions

- None. The current repo and host evidence both point to a straightforward provider retirement.
