# Private Ghostship integration

One container runs the official relay and a stdio MCP child exposing eight Keep,
four Amazon tools and integration status. The tunnel is
`tunnel_6ac0806704cc819188e52213f9afd272`; the owner has observed Keep/Amazon tool
discovery in ChatGPT. Runtime relay credentials live in Bitwarden and the
age-encrypted scoped secret bundle, outside Git plaintext and the Nix store.
No public origin, inbound port or browser debugging endpoint is exposed.

Keep executes directly in the separate host service. `account: User|Agent`
selects the configured profile mapping; User → Assistant and Agent → Default.
Each mapping declares its Google `authuser` index. Update it if sign-in order
changes. The model does not choose profile IDs, manager addresses or executables.
Cookies and sessions stay on the host. Amazon read tools use the existing
anonymous shopping client and runtime home ZIP, preserving unknown costs.

## Deployment

Build pinned agent and assistant sources, then run
`nix develop .#ci -c scripts/check` and build the actual Chill Penguin target.
Stage new Nix files before evaluating. Preserve the active T3 session using
[the session guard](container-workflow.md#preserve-the-active-t3-code-session).
If full activation touches T3, install only the exact integration unit and keep
its candidate build rooted. Do not stop T3 or the browser manager.

The broker resolves the current browser-manager IP through Podman before startup.
CloakBrowser is used only for authentication acquisition or refresh. The generated
API client executes every note operation with private cached sessions in
`/var/lib/ghostship-keep/sessions`. It leases only its own authentication tabs and
never stops an existing browser profile. Session caches are excluded from backups.
UIDs are MCP 62020 and host broker 62021; the operation socket is group-scoped.
The non-root container has a read-only root, scoped tmpfs/state, no capabilities
and only relay files, application state and the operation socket directory mounted.

## Verification and metadata

Keep writes execute and read back immediately. Duplicate idempotency keys return
stored results; changed payloads/revisions conflict. A lost write response remains
uncertain until positive read reconciliation. Preserve the SQLite operation
records across restarts. Health probes inspect only process state; measure relay
polling, local MCP readiness and live account calls separately.

Open the Ghostship connection at ChatGPT Plugins and select Refresh after a
schema/description change, then start a fresh conversation. Verify list/search/get,
create/update/checklist/archive/delete-to-trash and Amazon search/item/destination/comparison.
An upstream sign-in or refusal is reported as unavailable or upstream_blocked,
with no fabricated data. Connection discovery alone does not prove live calls.

## State and rollback

`/var/lib/ghostship-keep` contains note content, idempotency and result records;
keep private and persistent and exclude from general backups. Relay state is
scoped to `/srv/apps/ghostship-private-integrations` and excluded from backups.
There is no automated purge. Stop only the new integration container/projection
and broker when replacing their reviewed prior units/image. Retain Keep state
and leave T3 and its inner runtime running. Runtime-only unit activation does
not establish reboot persistence; finish declarative activation in a safe window.

## Live evidence (2026-10-03)

The actual Chill Penguin MCP child discovered all 13 tools. Personal User API
calls passed list/search/get, disposable note create/update, checklist toggles
with unrelated items preserved, archive and delete-to-trash read-back. Duplicate
creates returned their saved result. Synthetic tests verify interruption recovery;
The actual connected GhostShip plugin also passed list/create/get/update/archive
and cold authentication recovery. Its cached tool metadata still needs refresh
before deletion is available in a fresh ChatGPT conversation.
CloakBrowser only acquires authentication; API calls reuse private cached sessions.

Amazon search/item/delivery/comparison ran live with partial coverage. Shipping,
mandatory fees and comparable delivered subtotals remained unknown; comparison
returned no verified winner. The relay passed readiness and authenticated polling.
T3 container, start time, service PID and inner application PID stayed unchanged.
The scoped units are active; full-system activation remains deferred by the session
guard, so reboot persistence is not yet established. Scoped rollback retains Keep
state and restores the previous integration unit/image roots.
