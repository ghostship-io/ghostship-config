# Private Ghostship chat integrations

## Ownership and audit baseline (2026-10-03)

| Owner | Inspected revision | Canonical responsibility |
|---|---|---|
| ghostship-agent | `2f146b3e031e530ee84773a4df98119c75413264` | Google/shopping registry, wrappers, Printing Press semantic clients, account-neutral MCP SDK adapters and OCI image |
| ghostship-assistant | current work branch `6737bde`, historical main `4d47b44` | Personal identity, disabled activation policy, complete-operation Keep broker, owner decisions and durable audit |
| nixos-config | `4867fb03057f5f1cb6c848132aaa2d6bd4051319` | Chill Penguin ARM64 deployment, private sockets, runtime projection, app registry and rollback |

The historical assistant audit point was not reset over newer work. Its prepared
profile-broker implementation is reused and main is merged into the implementation
branch. Exact deployed implementation pins are in `flake.lock`.

| Capability | Implementation | Account/authorization | Live evidence |
|---|---|---|---|
| Keep list/search/get | Packaged semantic client and protected socket adapter | Owner blocked: master disabled, reviews pending; owner scope/activation consent recorded, runtime disabled | Synthetic protocol and broker evidence only |
| Keep create/update/checklist/archive | Durable one-use approvals; stable create/checklist IDs and revision preconditions | Owner blocked; each action needs a separate root-SSH owner decision | Synthetic approved writes and interruption reconciliation only |
| Amazon search/item | Existing anonymous Printing Press client; explicit shopping authorization | Anonymous read route authorized; no personal Prime claim | Live evidence recorded below; no personal-account inference |
| Amazon delivery/comparison | Partial provider coverage; transient destination ZIP, unknown fees preserved | Runtime home ZIP; alternate quotes do not alter personal settings | No complete checkout total or global-lowest claim |
| Official private relays | One supervised combined stdio child in one container | Blocked until owner provisions one tunnel ID/Use key and owner-only workspace association | Local configuration validation; no claimed OpenAI connection |
| ChatGPT selectable connections | One Ghostship registry entry and combined explicit tool allowlist | Actual owner entitlement and discovery still unverified | Requires fresh authenticated owner conversation |

Audit findings reproduced and addressed:

- `set -e` escaped cached-session diagnostic/refresh handling. Status is now
  explicitly captured; typed authentication exit 4 allows one leased refresh,
  with read-only replay. Cancellation exits and non-auth failures are preserved.
- Historical assistant `run` denial is intentional and still enforced. A new
  complete-operation Keep broker supplies the missing narrow execution boundary;
  packaging never enables it.
- Google declarations advertised User paths despite Agent-only JSON entries.
  Registry, generated declarations, dispatch and tests now agree. Personal
  generated session export through the shared wrapper is denied before access.
- Amazon delivery inferred zero mandatory fees from purchasability. It now
  requires explicit evidence; variant/seller/condition changes invalidate the
  quote. Coverage remains partial.
- The internal shopping session bridge remains provider-private and is omitted
  from the MCP package/image. No credential-bearing session tool is exposed.
- Existing retail profile-broker caller JavaScript remains an activation blocker
  for that broader scope. This integration uses anonymous Amazon and fixed
  Google broker operations, and does not activate retail browser access.

Trace: app registry selects profile → SDK allowlist/schema → fixed semantic
client/provider → mandatory shopping authorization or assistant admission →
immutable packaged executable → protocol, contract, socket and pricing tests.
Agent-account Google evidence does not establish Owner readiness.

## Runtime and state

One Podman OCI container, `ghostship-private-integrations`, runs as UID/GID 62020
with read-only root, bounded tmpfs/resources and no capabilities or inbound ports.
The immutable image contains pinned MCP SDK 1.15.0 and OpenAI runtime 0.0.15
(release source `a390c168ff1b2d14e73a95991c186c6aba3ff5a0`, per-architecture
archive hashes in the agent Nix package). The official poller flavor uses outbound
HTTPS and needs no cloudflared companion. It performs no startup downloads.

One relay has a scoped configuration/ID and loopback-only health port 8081,
fixed stdio children and bounded restart backoff. A subreaper kills and reaps
orphan stdio children before replacement. Container liveness checks only a fresh
supervisor heartbeat. Local relay `/readyz`, MCP discovery, authenticated control-plane connection and personal readiness are
separate checks; liveness performs no authentication or account operation.

The image sees only scoped `/run/ghostship-integrations`, the operation socket
directory `/run/ghostship-keep`, and dedicated `/srv/apps/ghostship-private-integrations`
state. Relay keys are 0400, file-referenced, and stripped from MCP subprocess
environments before Python starts. No host home, browser database, profile socket,
Podman socket, secret collection, public hostname or origin is mounted/exposed.

Host UID 62021 owns the private broker. `/var/lib/ghostship-keep` persists canonical
requests, decisions, one-use consumption, idempotency/result linkage and redacted
audit across restarts; it contains personal content after activation. Retain it
on rollback, including uncertain requests. It is outside general app backups;
relay app state is explicitly excluded too. No automated purge is implemented.
Owner controls retention and encrypted offline backup. Cookies/configurations are
transient private host files, removed after each semantic operation.

The profile broker resolves CloakBrowser's actual Podman IP on host startup;
container DNS is not assumed to resolve on the host. It is not enabled by this
module. Personal master and independent review gates still precede every access.
MCP cancellation can stop waiting; it cannot revoke an accepted durable upstream
write. Retrieve its existing status/reconcile rather than resend with a new key.

## Owner-controlled connection steps

Official references, checked 2026-10-03:
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[official client](https://github.com/openai/tunnel-client),
[developer mode](https://developers.openai.com/api/docs/guides/developer-mode),
[connection and metadata refresh](https://developers.openai.com/plugins/deploy/connect-chatgpt).
Developer-mode documentation lists personal plans with read/write support, but
that does not prove this account has tunnel entitlement or a workspace mapping.
No trusted owner approval attestation is documented, so ChatGPT confirmation is
not accepted by the broker as personal mutation authorization.

1. In Platform Settings → Organization → Tunnels, select the intended organization
   and establish its association with the owner's ChatGPT workspace. Restrict
   tunnel Use permission to the intended owner/required runtime principal; do not
   expose this fixed personal principal to a shared workspace. Read+Manage is
   required to provision, Use to run/select. If owner-only restriction cannot be
   demonstrated, personal activation stays blocked.
2. Create one private Ghostship tunnel. Put its `TUNNEL_ID` and least-privilege
   runtime `API_KEY` into the encrypted `ghostship-relay.env.age` source using
   `secret-edit ghostship-relay`. The scaffold is empty and fails closed.
   Never put values in Git, Nix expressions, CLI arguments, logs or chat.
3. Deploy committed configuration using the session guard, then start only the
   new container after projection succeeds. Confirm local readiness separately
   from authenticated tunnel polling and MCP discovery.
4. Enable ChatGPT Settings → Security and login → Developer mode. At
   `https://chatgpt.com/plugins`, plus → name **Ghostship**, Connection **Tunnel**,
   select/paste its ID. Inspect eleven Keep/Amazon tools plus `integration_status`.
   This is one private developer-mode connection, with no marketplace submission.
5. Obtain assistant security/final PASS reviews for the exact revision and the
   explicit owner Keep-only activation (consent recorded 2026-10-03; reviews still pending). Record two synthetic read-only runs with
   commit/evidence and bind the registered Assistant identity/profile. Do not
   activate unrelated Google/retail services. Each live write is separately
   inspected/accepted using `ghostship-keep-approve` over owner-authenticated root
   SSH, as documented in the assistant repository.
6. Start a fresh chatgpt.com conversation with Ghostship selected. Check Keep
   list/search/get, then an individually approved uniquely marked disposable
   note/checklist create and update with read-back. Test denial and uncertain-write
   reconciliation. Archive/cleanup needs its own decision. Check Amazon search,
   returned ASIN item/destination delivery and comparison; retain unknown costs.

After metadata changes deploy the new MCP server, open the Ghostship connection at ChatGPT
Plugins, select **Refresh**, inspect changed schemas/tools, and start a fresh
conversation. This is the documented procedure; actual account behavior remains
unverified until owner connection is available.

## Session-preserving rollout and rollback

Before any activation record T3 ID/start time/MainPID and inspect candidate units,
activation hooks and dependencies. If full switch could interrupt T3, install
only the exact new Nix-generated service(s) via root SSH and retain their build
with a GC root. Defer the full switch. Do not restart T3, its inner runtime,
CloakBrowser, or unrelated services to make this deployment work.

Stop-before-start prevents two live instances using the tunnel ID. Rotation
validates the scoped projection before replacing files; restart only the new
integration container. A malformed projection leaves prior runtime files intact.
For rollback stop `podman-ghostship-private-integrations.service` and, if needed,
`ghostship-keep-broker.service`; restore the previous pinned image/unit and scoped
credentials, preserving `/var/lib/ghostship-keep`. Keep personal access disabled
until reviewed. Do not delete approval/idempotency state or run a full-system
rollback that can affect the active T3 session.

## Verification evidence

The final implementation handoff records build paths, host unit state, tests,
PRs and all remaining connection blockers. Synthetic, local MCP, relay and
ChatGPT evidence are reported separately. Production reboot testing is skipped
under the active-session constraint; restart/socket and write recovery use
isolated synthetic services instead.

CI uses two repository-specific read-only deploy keys, installed as Actions
secrets `GHOSTSHIP_AGENT_READ_KEY` and `GHOSTSHIP_ASSISTANT_READ_KEY`. The bootstrap
fetches exact locked revisions and verifies each NAR hash before substituting CI-only local Git source locks. Private keys are temporary runner files and are never passed to Nix or included in its store. Published refresh PRs restore the portable source locks. No broad GitHub token or owner-created read PAT
is required. Both keys were registered read-only and their exact pinned source
hashes verified through real SSH. Rotate each by registering a replacement key,
replacing its Actions secret and verifying CI before revoking the old key.
Revoke through the source repository's Settings → Deploy keys. Provisioned key
IDs: agent `165231346`, assistant `165231352`. GitHub may revoke keys if the
credential that registered them is revoked. Fork PRs do not receive these secrets;
private-source builds for them need a separately trusted review path.

Historical two-relay deployment evidence (2026-10-03, before consolidation):

- Agent implementation `86d679fc83e57a0f9acb9ddd312561ead37c076e`, assistant
  `7658bb5f965eed87620e60f79c6f87fad9143e06`; linked agent PR #10 and assistant PR #9.
- Final ARM64 image tag `dsd4nh816z2vnam36q3qswbav29ps026`, loaded image ID
  `c4713bc7a2a69d3f338524a7313469214c377405cfb0638acbefddc50f71b019`,
  User `62020:62020`. Both profiles initialize/discover from read-only Podman,
  with no worktree mount. Keep returns policy denial through the mounted socket,
  including after isolated broker restart; forged `confirmed` input is rejected.
- Full Chill Penguin configuration built with `--impure` on the actual host.
  Dry activation would stop Cloudflared and starts the T3 deployment helper, so
  full-system activation is deferred. Only the new broker's exact Nix-generated
  runtime unit is installed; its GC root preserves the closure. It is active with
  personal access disabled. Runtime-linked unit installation does not enable
  reboot recovery; the committed NixOS activation remains necessary for that.
- T3 identity before/after scoped installation: container
  `134b90bb20700b6180a225b997f386dbf1a1d6339d17da22be1a57884d0d50d7`,
  start `2026-10-02 21:17:42.5084494 +0000 UTC`, MainPID `2195037`.
- Anonymous Amazon search/item read at 02:50 UTC returned ASIN `B0DDWN12RL`
  and a partial observation. Destination quote at 02:51 UTC returned
  `upstream_blocked`; the live sequence stopped. Shipping, fees, currency and
  personal eligibility stayed unknown, with no ranked winner or checkout total.
- Agent: 446 Python tests (three existing skips), typed Google shell recovery,
  Go semantic HTTP conflict and no-write-replay tests, fleet, shellcheck, links and flake evaluation.
  Assistant: declared verification suite including 17 Keep core/socket tests;
  synthetic approved writes, conflict, single-use/expiry/replay and interruption
  recovery. NixOS: required scripts/check, host-evaluation/config-tests/package,
  scoped credential rotation, shellcheck and redacted gitleaks. No production
  reboot, personal authentication/mutation or fresh ChatGPT conversation ran.
- Remote assistant verification passes. Fleet CI initially failed private SSH
  source fetch; GitHub-source token support replaces that path. Actual fleet CI
  still needs the owner-controlled read token. Agent repository defines no remote
  workflow; local declared checks are the available evidence.

All three PRs remain drafts while required access/review gates remain unresolved.
Infrastructure availability is not a declaration of personal ChatGPT readiness.

The final official-relay offline smoke launched both real stdio MCP children with
synthetic file-referenced credentials, no network, read-only root and the same
scoped mounts. Both `/healthz` and `/readyz` returned 200 even while disconnected.
This establishes local relay/MCP startup, **not** OpenAI connection. Verify
authenticated tunnel polling and fresh ChatGPT discovery before reporting relays
connected. TERM forwarded to both groups, reaped children and exited 0. The
temporary smoke container was removed; no production relay is running.

Final hardening proves Google mutation transport never retries network ambiguity,
429/5xx or redirects; explicit read queries retain bounded recovery. Session
helpers preserve identity failures instead of masking them with cleanup. The
broker reuses confirmation validators and the hash-chained audit, and reconciles
the generated client’s exact title/text/checklist representations without replay.
Official relay and MCP child crash recovery both passed in the disposable offline
container; neither test establishes authenticated OpenAI connectivity.

## Single-connection migration

The owner superseded the two separately selectable connections with one Ghostship
connection. Deployment now uses one `ghostship` profile, relay, app entry and
`ghostship-relay` secret bundle. The original empty relay scaffolds had no live
credentials and are replaced; no provisioned tunnel or account data is deleted.
Keep/Amazon local profiles remain for standalone verification. New services must
add explicit schemas, deterministic adapters and policy rather than model-selected
upstreams. Reverting this commit restores the prior two-relay topology; retain
Keep approval state and stop the new integration before replacing any relay.

Owner credential/activation consent covers Keep list/search/get with individually
approved create/update/checklist/archive and Amazon search/item/delivery/comparison
reads. Reviews, signed-in identity and per-action decisions remain independent.
GitHub admin access can install an Actions secret but the available classic token
has broad repository/workflow permissions; it is not projected into CI. Read-only deploy keys now provide the scoped CI credential.

Single-connection verification: 447 Python tests pass (three existing optional
skips); packaged SDK initialization discovers all eleven tools plus status.
Service routing and status retrieval are verified with synthetic clients, and a
generic approval tool is denied. Image `5dikk4niw9d654zp6kgq830k54wldms2`
(ID `52507eff2350fb46ee6e9da0c26bdff83d97816de9371f447fabeb5ade020ffe`)
runs independently on the ARM64 host; disabled Keep access and forged confirmation
fail through the actual socket before/after broker restart. The one real official
relay and its MCP child both recover after deliberate crashes in the disposable
network-isolated container. No live relay credential or personal access is used.
