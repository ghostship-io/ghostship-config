# Shared agent memory workspace (Basic Memory)

`modules/self-hosted/agent-memory.nix` runs one pinned Basic Memory v1.0.0
service for the shared active workspace used by Wisp and the orchestrator. It
is **dark by default**; enabling it is the owner's security decision. The
connector side is `notes_see` / `notes_act` / `notes_state` / `notes_run` in
the native Go connector.

## Boundary

- One private Podman network `agent_memory_net` (10.89.23.0/24, `--internal`,
  no egress) with exactly two members: `t3code` and `agent-memory`.
- No published port, Cloudflare route, public DNS or muximux entry. The
  upstream MCP endpoint is unauthenticated by design; the network and the
  authenticated connector are the only boundary.
- One private volume `/srv/apps/agent-memory` (0700, uid/gid 3000) holding
  config, SQLite and Markdown. It is inside the existing `/srv` Btrfs snapshot
  and restic backup; that is ordinary task data, not a new access grant.
- No new credential, provider token or GitHub grant.

## Build and enable

Build on the host (the image is never pulled at runtime). The base is the
official v1.0.0 OCI index for upstream commit
`c9bd187b83baba549d5cd16bacc180f8023d51c8`; the derived image applies the
durability patch and pre-bakes the embedding model so the service has no
egress:

```sh
podman build -f modules/self-hosted/agent-memory.Containerfile \
  -t localhost/agent-memory:1.0.0 modules/self-hosted
```

Then enable `ghostship.agentMemory.enable = true` in the reviewed host
configuration. The `agent-memory-projects` oneshot creates `agent-memory` and
`agent-memory-test` with `--network=none` before the server starts; a repeat is
idempotent. The production workspace starts empty.

## Durability contract

An acknowledged `bm_write`/`bm_edit` means the accepted `note_content` row is
committed with `BASIC_MEMORY_SQLITE_SYNCHRONOUS=FULL` (WAL). The Markdown
materializer is asynchronous:

1. `accept_write` commits the accepted row (`pending`) before the tool returns.
2. The materializer writes a temp file, fsyncs it, renames it, and fsyncs the
   parent directory (the `agent-memory-fsync.patch` change), then publishes
   `file_write_status="synced"` in a FULL transaction.
3. If the process or host dies before `synced`, startup recovery re-drives
   `pending`/`writing`/`failed` rows from the accepted DB content and rewrites
   the file. Verified locally: a row forced to `writing` with its file removed
   was rewritten from the DB and returned to `synced`.
4. If the status reached `synced`, the file bytes and rename were already
   durable, so a power loss cannot lose the acknowledged write.

Residual, explicit: the Markdown file is the source of truth for *external*
edits. Deleting or corrupting a file after a successful `synced` write is an
external change, not power loss; the next scan can treat it as such (verified
on the unpatched source: a missing file removed the note, a stale file replaced
the accepted body). That is why the fsync patch is part of the image. A move's
rename is not fsynced by this patch; archive is status-authoritative, so a lost
move leaves the item archived in `active/` and is reconciled by read-back and a
move retry, never by a silent delete.

## Verification

Record each result as PASS, FAIL or UNKNOWN; do not infer one from another.

```sh
podman exec agent-memory basic-memory config get sqlite_synchronous
# expect: FULL (source: environment)

curl -fsS http://127.0.0.1:8000/mcp ...   # in-network only; no host port exists
```

- Cold start: time `podman-agent-memory` start to a successful MCP
  `initialize`; record image size and build time.
- Restart: accept a write, restart the container, read the same checksum.
- Crash recovery: force a row to `writing` with the file absent in a **test
  project** copy, restart, confirm the file is rewritten from the DB.
- Backup/restore: restore the `/srv` snapshot to a scratch path, start a
  second Basic Memory process against it, and compare note checksums.
- Contention: two concurrent edits with the same checksum; exactly one wins
  and the other gets `REVISION_CONFLICT` with the winner's checksum.
- Fresh context: a new orchestrator/Wisp thread asked to design an agent tool
  retrieves the `policy/` BladeBro pointer and applies it without the owner
  restating the standard.

## Rollback

Disable `ghostship.agentMemory.enable`. The container and private network are
removed; `/srv/apps/agent-memory` is retained. The connector simply loses the
`notes_*` tools when `GHOSTSHIP_NOTES_ENDPOINT` is absent. No public route
exists to withdraw.
