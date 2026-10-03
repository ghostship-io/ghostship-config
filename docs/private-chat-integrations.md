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
| Keep list/search/get | Packaged semantic client and protected socket adapter | Owner blocked: master disabled, reviews and Keep-only activation absent | Synthetic protocol and broker evidence only |
| Keep create/update/checklist/archive | Durable one-use approvals; stable create/checklist IDs and revision preconditions | Owner blocked; each action needs a separate root-SSH owner decision | Synthetic approved writes and interruption reconciliation only |
| Amazon search/item | Existing anonymous Printing Press client; explicit shopping authorization | Anonymous read route authorized; no personal Prime claim | Live evidence recorded below; no personal-account inference |
| Amazon delivery/comparison | Partial provider coverage; transient destination ZIP, unknown fees preserved | Runtime home ZIP; alternate quotes do not alter personal settings | No complete checkout total or global-lowest claim |
| Official private relays | Two supervised stdio children in one container | Blocked until owner provisions two distinct tunnel IDs/Use keys and owner-only workspace association | Local configuration validation; no claimed OpenAI connection |
| ChatGPT selectable connections | Separate registry entries and explicit tool allowlists | Actual owner entitlement and discovery still unverified | Requires fresh authenticated owner conversation |

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

Two relays have distinct configurations/IDs, loopback-only health ports 8081/8082,
fixed stdio children and bounded restart backoff. A subreaper kills and reaps
orphan stdio children before replacement. Container liveness checks only a fresh
supervisor heartbeat. Relay `/readyz`, MCP discovery and personal readiness are
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
2. Create two private tunnels, one for each connection. Put each distinct
   `TUNNEL_ID` and least-privilege runtime `API_KEY` into its own encrypted source:
   `ghostship-keep-relay.env.age` and `ghostship-amazon-relay.env.age`, using the
   repository's existing secret workflow. Current encrypted files are empty
   scaffolds and deliberately fail closed. Never put values in Git, Nix expressions,
   CLI arguments, logs or chat. No matching OpenAI credential was available in the
   inspected vault metadata.
3. Deploy the committed configuration using the session guard, then start only
   the new container after scoped projection succeeds. Confirm both loopback
   `/readyz` endpoints from inside the container; confirm MCP discovery separately.
4. In ChatGPT Settings → Security and login enable Developer mode. At
   `https://chatgpt.com/plugins`, plus → name **Ghostship Keep**, Connection
   **Tunnel**, select/paste its ID; repeat for **Ghostship Amazon** with the other
   ID. Inspect seven Keep tools/four Amazon tools plus their own status tool.
   No public marketplace package or frontend is required for these private
   developer-mode connections.
5. Obtain assistant security/final PASS reviews for the exact revision and the
   explicit owner Keep-only activation. Record two synthetic read-only runs with
   commit/evidence and bind the registered Assistant identity/profile. Do not
   activate unrelated Google/retail services. Each live write is separately
   inspected/accepted using `ghostship-keep-approve` over owner-authenticated root
   SSH, as documented in the assistant repository.
6. Start a fresh chatgpt.com conversation with both selected. Check Keep
   list/search/get, then an individually approved uniquely marked disposable
   note/checklist create and update with read-back. Test denial and uncertain-write
   reconciliation. Archive/cleanup needs its own decision. Check Amazon search,
   returned ASIN item/destination delivery and comparison; retain unknown costs.

After metadata changes deploy the new MCP server, open each connection at ChatGPT
Plugins, select **Refresh**, inspect changed schemas/tools, and start a fresh
conversation. This is the documented procedure; actual account behavior remains
unverified until owner connection is available.

## Session-preserving rollout and rollback

Before any activation record T3 ID/start time/MainPID and inspect candidate units,
activation hooks and dependencies. If full switch could interrupt T3, install
only the exact new Nix-generated service(s) via root SSH and retain their build
with a GC root. Defer the full switch. Do not restart T3, its inner runtime,
CloakBrowser, or unrelated services to make this deployment work.

Stop-before-start prevents two live instances using one tunnel ID. Rotation
validates both scoped projections before replacing files; restart only the new
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
