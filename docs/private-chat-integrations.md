# Private Ghostship integration

One private container runs the official relay and one persistent Ghostship MCP
runtime. Coding clients and the relay connect to independent SDK sessions on the
same private Unix endpoint. Tool definitions and handlers come from the pinned
`ghostship-agent` capability catalog. The tunnel is
`tunnel_6ac0806704cc819188e52213f9afd272`. Runtime relay credentials live in
Bitwarden and the age-encrypted scoped secret bundle, outside Git plaintext and
the Nix store. No public origin, inbound port or browser debugging endpoint is
exposed. Cached client discovery needs its supported refresh independently of
a successful fresh-client discovery.
Keep executes in the separate host service. `account: User|Agent`
selects the persistent Agent Desktop Chrome identity: User → `personal` (port 9223),
Agent → `agent` (port 9222). The broker verifies the signed-in Google
account and resolves its current `authuser` index dynamically. Neither a
legacy profile ID nor a second Chrome process is required.
Cookies and sessions stay on the host. Create/update support separate title/body fields, checklist row patches, labels and PNG/JPEG/GIF images; search accepts a label/tag alone or with text. Drawings and reminders are excluded. Canonical shopping calls use the selected Agent Desktop browser identity and
runtime home ZIP, preserving unknown costs. Native controls, eligibility and
checkout evidence still need retailer acceptance; consumer migration is incomplete.

## Deployment

Build the pinned `ghostship-agent` and `nixos-config` revisions, then run
`nix develop .#ci -c scripts/check` and build the actual Chill Penguin target.
Stage new Nix files before evaluating. Preserve the active T3 session using
[the session guard](container-workflow.md#preserve-the-active-t3-code-session).
If full activation touches T3, install only the integration units required for
the migration while preserving the running T3 service and Agent Desktop sessions.

The `ghostship-desktop-bridge` service installs the desktop SSH key, pinned host
key and address into `/run/ghostship-integrations/`. The host Keep broker reads
that same contract using `GHOSTSHIP_BROWSER_DRIVER=desktop`. The private MCP
container joins both `ghostship_net` (T3 access) and `agent_desktop_net` (Chrome
access), and uses the same identity mapping. The generated API client executes
note operations using private cached sessions in `/var/lib/ghostship-keep/sessions`.
It leases its own authentication tab, never stops Chrome, and excludes caches
from backups.
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
schema/description change, then start a fresh conversation. Compare the discovered catalog and integration status from fresh coding and
OpenAI connections, then exercise the same browser, Google and shopping calls.
Fresh status success does not validate a cached schema or authenticated workflows.
An upstream sign-in or refusal is reported as unavailable or upstream_blocked,
with no fabricated data. Connection discovery alone does not prove live calls.

## State and rollback

`/var/lib/ghostship-keep` contains note content, supplied image bytes, idempotency and result records;
keep private and persistent and exclude from general backups. Relay state is
scoped to `/srv/apps/ghostship-private-integrations` and excluded from backups.
There is no automated purge. Stop only the new integration container/projection
and broker when replacing their reviewed prior units/image. Retain Keep state
and leave T3 and its inner runtime running. For boot rollback, restore the system profile from
`/nix/var/nix/gcroots/ghostship-private-integrations-boot-previous` and run that
generation's `switch-to-configuration boot`; do not reboot from an active T3 session.

## Live evidence (2026-10-03)

The actual Chill Penguin MCP child discovered all 13 tools. Personal User API
calls passed list/search/get, disposable note create/update, checklist toggles
with unrelated items preserved, archive and delete-to-trash read-back. Duplicate
creates returned their saved result. Synthetic tests verify interruption recovery;
The actual connected GhostShip plugin also passed list/create/get/update/archive
and cold authentication recovery. Its cached tool metadata still needs refresh
before deletion is available in a fresh ChatGPT conversation.
These October 3 observations predate the Agent Desktop cutover. They do not
establish that the new SSH bridge and broker deployment have passed live testing.

Amazon search/item/delivery/comparison ran live with partial coverage. Shipping,
mandatory fees and comparable delivered subtotals remained unknown; comparison
returned no verified winner. The relay passed readiness and authenticated polling.
T3 container, start time, service PID and inner application PID stayed unchanged.
The scoped units are active. Merged sources are on all three remote `main` branches.
The native host build with `--impure` includes `/boot/asahi` firmware; generation
238 is installed as the next-boot default through `switch-to-configuration boot`.
All three Ghostship units match this generation. Persistence is configured; reboot
recovery has not been exercised. The live full-system switch remains deferred by
the session guard because its activation hooks schedule T3 deployment. Scoped
rollback retains Keep state and restores the previous integration unit/image roots.

Expanded content was verified with disposable personal API notes: separate
title/body, initially checked boxes, stable row edits/appends/removals, labels,
image upload/read-back/removal and preservation of unrelated checklist rows.
The deployed MCP container also passed tag-only and combined text/tag search,
missing-tag empty results, rich create/update, image replacement/removal, duplicate
requests, stale-revision conflicts and fixture cleanup. An uploaded image with a
transformed stored byte size was positively reconciled after the service restart
without replay. The connected GhostShip tool read back the updated test note.
Refresh connection metadata to discover the new create/update/search fields.
