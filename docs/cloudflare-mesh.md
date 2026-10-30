# Private fleet networking

Refs #707. The owner authorized rollout, enrollment and Cloudflare configuration.
Preserve the existing Chill Penguin tunnel throughout. Use the existing
**Free** Zero Trust plan. This configuration purchases nothing. Mesh is beta;
NixOS packages the headless Linux client, but installed WSL/ARM64 compatibility
and routing remain UNVERIFIED until tested on the actual hosts.

## Startup and recovery

`launch-octopus`, `armored-armadillo`, and `chill-penguin` each own a distinct
Mesh identity. Native system services start with the host, including every WSL
distribution start. No Windows scheduled task or interactive login is needed
for Linux networking. Starting Windows does not start a stopped WSL distro.

DNS is split by domain through a loopback-only dnsmasq dispatcher. Only
`mesh.ghostship.io` goes to WARP's local DNS proxy; a failed private lookup
never falls back to normal upstreams. Ordinary Internet and LAN lookups keep
using the existing resolver information: Windows' `/mnt/wsl/resolv.conf` on
WSL, and resolvconf's existing network subscribers on the server.

WARP gets a private resolver file inside its service mount namespace and
cannot change host DNS through D-Bus. Its root-only registration state and
umask remain unchanged. WSL resolver generation is disabled because the local
dispatcher owns the host resolver. Verify a distribution restart, Windows DNS
reachability and fresh DNS queries before accepting startup behavior.

Gateway DNS overrides resolve the three known Mesh names. Block unknown names
under the private zone so they are not forwarded to public DNS. Prove normal
Internet/LAN resolution with WARP stopped, private resolution while connected,
and no private-zone fallback during an outage before activating another host.
Run the isolated DNS routing/outage check with
`nix develop .#ci -c python3 tests/integration_mesh_dns.py`.

WARP reconnects natively. The 30-second health timer requests connection and
restarts only WARP after three failed checks, at most once per ten minutes.
For roaming clients, keep captive-portal detection enabled, the client switch
unlocked and automatic connection enabled in the managed device profile
(current timeout: 180 seconds). Portal sign-in remains an owner action.
Normal DNS and portal browsing remain independent of the Mesh connection;
recovery preserves registration when the network becomes usable again. A VPN
or network that blocks all Cloudflare transport cannot be repaired locally;
recovery resumes when that restriction ends. Actual Wi-Fi changes, VPN
coexistence and captive-portal recovery still require installed-host checks.
It never deletes registration or restarts T3. RPC startup delays defer initial
enrollment. An uncertain enrollment is reconciled, never repeated blindly.
Consumer registrations are refused rather than replaced. Before retrying an
uncertain enrollment, inspect native registration and the Cloudflare node;
never automatically delete `enrollment-attempted` or native `reg.json`.
Verify the enrolled Linux client's JSON account type and organization during
rollout; an unknown schema is refused without changing the identity.

Keep native MASQUE HTTP/3 with HTTP/2 fallback enabled. When testing a
UDP-blocked network, block UDP to the tunnel endpoints across all ports:
the client can recover by choosing another UDP port before needing TCP.
The local preflight verified TCP fallback with the registration and host DNS
unchanged; this does not replace actual VPN and captive-portal acceptance.

Nodes can initiate connections to each other's Mesh IPs. This does not need
LAN/subnet advertisements or IP forwarding. Use MASQUE with only
`100.96.0.0/12` included, preserving normal Internet and existing LAN routes.
Windows apps need a Windows client enrolled in the same organization to reach
remote Mesh IPs; T3 Desktop can reach its own WSL backend through localhost.

SSH and HTTPS are allowed on `CloudflareWARP`, with password SSH disabled.
WSL adds no global incoming port. The server retains its existing SSH route
during rollout: remove its global allowance only after another device verifies
Mesh SSH, under separate approval. HTTPS has no global firewall allowance.

## One-time provisioning

Sign in to `ghostshipio` at <https://one.dash.cloudflare.com/>. Verify the plan
is Free and stop if any operation requires a paid upgrade. Do not enable paid
add-ons, WAN, T3 Connect or paid certificates for this setup.

1. Enable unique device IPs, enrolled-device reachability, and Gateway TCP/UDP
   proxying. Set MASQUE and the Mesh split-tunnel range on each node/client.
   Set automatic connection in the Windows managed device profile.
2. Establish default-deny Mesh network policy, with higher-priority allowances
   for the owner's devices and the three node identities on TCP 22/443 in both
   initiating directions. Enrollment alone must not authorize other services.
3. Create three separately named Mesh nodes. Reusing one token across hosts
   makes replicas, not independent nodes. Record each node's actual Mesh IP.
4. Set Gateway DNS overrides for `launch-octopus.mesh.ghostship.io`,
   `armored-armadillo.mesh.ghostship.io` and `chill-penguin.mesh.ghostship.io` to
   their corresponding Mesh IPs. Publish no public A/AAAA/CNAME for these names.
5. Provision a token scoped to Zone DNS Edit and Zone Read for `ghostship.io`.
   Free Let's Encrypt DNS-01 certificates renew automatically; no HTTP challenge
   port or paid certificate is needed. Activation accepts ACME and WARP terms
   through the managed options.

Provision these root-owned files outside Git/the Nix store, mode `0600`, with
secret parent directories mode `0700`. Never print their contents.

| File | Content |
| --- | --- |
| `/var/lib/ghostship-mesh/node-token` | This host's unique Mesh node token |
| `/var/lib/ghostship-mesh/cloudflare-dns-token` | Scoped DNS token for automatic ACME renewal |
| `/var/lib/ghostship-nix/github-nix.conf` | `access-tokens = github.com=` followed by a read-only private-source token; loaded by WSL upgrade units through systemd credentials |
| `/var/lib/ghostship-mesh/peers.json` | Other nodes' actual Mesh IPs, as a nonempty list of objects with `host` and optional `port` (default 22) |

Until the peer list exists, health reports routing **unverified**. Failed peer
probes report degraded reachability without restarting healthy local WARP.
Sleeping WSL peers are unreachable. Local Connected status and one-way checks
do not establish bidirectional routing.

## T3 and engineering

HTTPS proxies WebSockets to the existing loopback worker. On Chill Penguin it
resolves the existing `t3code:3773` gateway through Podman DNS, publishing no
container port. The Mesh module does not alter the T3 image configuration;
the shared input refresh can rebuild it, so the server's existing exact-image
acceptance and restart gates still apply. Native T3 pairing remains mandatory.
Keep TLS verification enabled and verify certificate issuance before pairing.

Pair each Windows desktop and web client separately to the same private
backends to observe their shared environment state. Files, credentials and
databases remain on their owning host. Do not replicate live T3 SQLite files.
Optional server-to-server T3 links require separate native authorization.

Both WSL hosts link pinned `ghostship-engineering`, `ghostship-review` and
`ghostship-planning` skills into Codex/OpenCode, Claude and Antigravity discovery
paths. References remain with their immutable source. The full Ghostship server
runtime is not installed. Owner-directed work follows the owner's task and
proportionate checks; controller assignments retain their contracts. Provider
and GitHub authentication remain user-owned.

## Acceptance and rollback

Before activation, preserve the system generation and consistent backups of
`.t3`, affected Linux/Windows provider configuration and skills. Generation
rollback does not undo data migrations, skill deletions or Windows writes.
Provision credentials before enabling unattended private-source upgrades.
For a manual root build, set
`NIX_USER_CONF_FILES=/var/lib/ghostship-nix/github-nix.conf` for the rebuild
command as well; user GitHub authentication is not root authentication.

After activation, verify startup, stable identity, split
routes, DNS, valid TLS, authenticated T3 HTTP/WebSockets and a small provider
task. Test SSH/HTTPS in both directions between every pair of nodes, and verify
that LAN/public access to the new HTTPS endpoint is denied. Test daemon crash,
uplink outage, WSL stop/start and resume; identity and T3 data must persist.
Confirm Windows and web clients display the same running task/status.

Diagnostics: `systemctl status cloudflare-warp ghostship-mesh-health`,
`systemctl list-timers ghostship-mesh-health.timer`, `warp-cli --json status`,
`ip route`, and `/var/lib/ghostship-mesh/health.json`. Registration responses
contain credentials and must not be printed. Account policy, remote hosts and
installed networking stay UNVERIFIED until actual acceptance passes.

Rollback disables `ghostship.mesh.enable` and switches to the preserved
generation through an independent management route. Account route removal and
token revocation require approval. Retain registration state for reconciliation.
Retire old public worker tunnels only after all clients pass private pairing
and reconnect tests.

Sources: [Free plan](https://developers.cloudflare.com/mesh/platform/),
[account settings](https://developers.cloudflare.com/mesh/get-started/),
[node lifecycle](https://developers.cloudflare.com/mesh/guides/run-mesh-on-linux/),
[T3 private pairing](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md).
