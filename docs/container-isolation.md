# Per-container network containment

A containment policy states what one container may reach and turns that
statement into an nftables ruleset. It is the exploit-mitigation layer of
Chill Penguin campaign #102: when a container is suspected, the edges it can
use are already narrow, so a foothold cannot walk sideways through the fleet.

The mechanism is the one the FlareSolverr egress rules already use
(`modules/self-hosted/flaresolverr-egress.nft`): one `inet` table and one
`bridge` table per container, loaded by a systemd unit, replaced in a single
`nft` transaction. There is no controller, no listener, no database and no
eBPF program in it.

Nothing is enforced yet. The master switch
`ghostship.containerIsolation.enable` and every per-container switch default
to `false`, the policy catalogue is empty, and no host rule is touched until
an operator turns a policy on and the harness has run on the target.

## The two switches

`ghostship.containerIsolation.enable` is the master switch. It is off, so no
ruleset is generated, no unit is created and no container depends on
anything. Each policy under `ghostship.containerIsolation.policies` has its
own `enable`; a policy that is enabled while the master switch is off fails
evaluation instead of silently doing nothing.

A policy names:

- `container`: the OCI container it contains.
- `network` and `subnet`: the podman network and its subnet. The container
  has to join that network and no other, and its address and resolver have to
  be inside the subnet.
- `address` and `mac`: the identity the container is reachable under. The
  container has to start with exactly this `--ip` and exactly this
  `--mac-address`, once each.
- `edges`: the directed edges the container may use. Every edge names one
  peer, one protocol and one port.
- `observed`: edges that were seen in the flow collector. They are evidence.
  They never become rules (see below).
- `publicEgress`: the protocols and ports the container may use towards
  public addresses. Off by default: public egress is a decision.
- `dns`, `dnsServer`: the resolver the container may query over UDP and TCP.
- `ipv6`: `deny` by default. A container on an IPv4 network has no use for
  IPv6, and a link-local neighbour solicitation is an address leak.
- `ingress`: optional. When enabled, the container's own ports are reachable
  only from the peers it has edges with and from the ports listed here, and
  the replies of a connection that reached one of those ports are allowed.
  A container that serves inbound traffic needs this block; without it its
  replies are egress and are denied.

There is no `bridge` option on purpose: the rules are keyed by the container's
address and MAC, not by a device name. A device name that is wrong, recreated
or renamed cannot turn the policy into a no-op.

## What the rules do

Every container gets two tables, `inet ghostship_ci_<policy>` and
`bridge ghostship_ci_<policy>`, both at priority `-10`: after the flow
observer at `-20`, which keeps recording what is dropped, and before the
host's own firewall.

The `inet` chains cover routed traffic and are keyed by the container's
address:

- `forward` allows the container's approved edges, the declared public
  egress, and then denies every private and LAN destination and every other
  packet the container sends.
- `input` allows DNS to the declared resolver and the approved edges that
  point at the host, and denies the rest of the container's traffic to the
  host. Public egress is deliberately **not** repeated here: a host-bound
  public address is reachable only through an approved host edge or DNS, not
  because the container may reach the public internet on that port.

Under the ingress contract, each declared service port also gets one stateful
reply rule per chain: the container may answer a connection that reached that
port (`… sport <port> ct state established,related ct direction reply
accept`). Three things keep it narrow:

- the connection has to be tracked already, so a new connection cannot use it;
- the packet has to be in the **reply** direction of that connection, so a
  flow the container itself opened — even one whose source port happens to be
  the service port — is not a reply. A revoked edge therefore cannot be kept
  alive by the reply rule;
- only the declared service ports are named.

The direction is the tuple's direction, not an address comparison, so a
published port that is DNAT'd through the host still works: the container's
reply is the reply direction of that connection.

The `bridge` chains cover the traffic that never leaves the segment, keyed by
the container's MAC and address:

- `prerouting` binds the identity. A frame that claims the container's
  address from another MAC is dropped, the container's MAC may only claim
  the container's address, and IPv6 from the container is dropped.
- `forward` allows the approved edges on the bridge and denies everything
  else the container sends there.

Two details are easy to get wrong and are worth stating:

- The bridge family names the **bridge port**, not the bridge device, so a
  bridge rule can only be keyed by the frame's own MAC and address. The
  `inet` family names the bridge device, but the rules do not rely on it
  either: the address is the identity, and a rule that matches the address
  on any interface cannot be escaped by moving the container.
- A continuation is only allowed when the connection was opened by the
  container towards the peer. `ct original ip saddr` and
  `ct original ip daddr` scope it, so a flow the peer opened towards the
  container never becomes an egress exemption, and a flow that was opened
  before the policy was loaded stays denied unless the edge is approved.

## Admission is fail-closed

The oci-containers module builds the `podman run` argv from native fields
(`privileged`, `capabilities`, `networks`) *and* from `extraOptions`. Admission
therefore reads that argv, not a parallel list, the way Podman's pflag reads
it: `--flag=value` and `--flag value` are the same flag, `--net` is an alias of
`--network`, and capability names are case-insensitive with an optional
`CAP_` prefix. A policy is refused when:

- the container is privileged, in any spelling (`container.privileged`,
  `--privileged`, `--privileged=true`);
- it does not drop ALL capabilities explicitly (`--cap-drop=ALL`, or the
  native `capabilities.ALL = false`), or its explicit additions include
  `NET_ADMIN`, `NET_RAW`, `SYS_ADMIN` or `ALL`. Podman's default set comes from
  `/etc/containers/containers.conf`, which NixOS writes from
  `virtualisation.containers.containersConf` and which may name `NET_RAW`;
  a mutable global default must not be able to reach a contained container.
  The baseline is therefore explicit: drop ALL, add back only what the
  service needs. A capability that is both added and dropped is refused,
  because the result would depend on Podman's ordering. A container that
  keeps `NET_ADMIN` can change its own MAC; one that keeps `NET_RAW` can
  craft frames that claim any address; one that keeps `SYS_ADMIN` can
  `setns` into any network namespace whose handle it is given (a mounted
  `/proc/<pid>/ns/net`, for example) and leave the rules behind entirely.
  Any of them would make the identity binding meaningless;
- it joins anything but exactly one network, the one the policy names. The
  native `networks` list, `--network`, `--net`, a second attachment and an
  alternate attachment (`name:ip=…`) are all read the same way;
- its `--ip` or `--mac-address` appears more than once, or is not the
  policy's identity;
- its address or resolver is outside the declared subnet;
- the backend is not podman;
- the container is a rootless unit (`podman.user`) or passes pre-run podman
  flags (`--remote`, `--url`, `--root`). Both run the container in a network
  namespace the host's rules and the metadata helper do not see, so the
  bounded policy refuses them instead of trying to parse every global flag.

The generator refuses a policy it cannot hold, so a broken policy fails the
build instead of producing a ruleset that matches nothing.

## The network has to be the one the policy names

The policy binds a container's address on a network. Before a rule is loaded,
the policy unit reads the network's metadata (`podman network inspect`) and
checks that the network carries exactly the declared subnet.

The check deliberately does not require a bridge device. Netavark creates the
bridge when the first container attaches, so a gate that waited for the
bridge before the container starts would deadlock the first boot. The network
definition exists as soon as the network is created, which is before any
container starts.

## The lifecycle

`ghostship-container-isolation-<policy>` is a oneshot unit that loads the
ruleset and stays active. The container's unit gains three relations:

- `requires`: the container may not start when the policy unit is missing or
  failed.
- `after`: the policy is loaded before the container starts.
- `bindsTo`: when the policy unit stops, the container stops with it, and
  the container is stopped *before* the filter is removed. The filter is
  never lifted from under a running container.

The stop order follows from the container's `after` and `bindsTo` on the
policy unit, and the policy unit is never ordered after the container.

## Observations are evidence, not approvals

The flow collector (`modules/self-hosted/security-flows.py`) records the
connections a container opens. Those observations are useful, but a flow
that was seen is not a flow that was reviewed. The policy therefore keeps
`observed` entries apart from `edges`:

- An observation never becomes an allow rule.
- The generated manifest lists every observation that no approved edge
  covers under `unresolved`. That list is the review queue.
- Free text fields (an edge's `purpose`, an observation's `category`) are
  checked: a URL or an address in them is refused. The repository is public,
  so a policy names structural service names and categories, never
  coordinates.

## The harness

`tests/check_container_isolation.py` proves containment with real packets.

- `selftest` runs without privileges. It checks the model, the admission
  rules, the rendered ruleset and the network metadata gate: an unsupported
  topology, an ambiguous identity, an unsafe capability set, an address
  outside the subnet, a coordinate in a free text field or a network whose
  metadata names another subnet must be refused, and an observed edge must
  not reach the ruleset.
- `harness` runs as root on the target. It builds a disposable topology in
  its own network namespaces, loads the generated ruleset inside the router
  namespace only, and removes every namespace, bridge and table with the
  run. The host's own rules, networks and containers are never touched.

The harness proves:

| Case | What it shows |
| --- | --- |
| approved same-bridge edge and its reply | the permitted edge carries traffic in both directions |
| approved routed edge | the same for a peer behind the router |
| same-bridge peer on another port | denied |
| same-bridge peer that is not approved | denied |
| host service on the bridge gateway | denied |
| private LAN address | denied |
| public address on a port outside the egress list | denied |
| a host public address on the approved egress port | denied: public egress is forwarded traffic only |
| an approved host edge | allowed, including from the host-bound input chain |
| a declared ingress port, from the bridge and from a routed peer | complete request and reply |
| an approved, already tracked flow whose edge is removed, with the client's source port equal to a service port | the second request is denied |
| DNS over UDP and over TCP | allowed |
| public egress on the declared port | allowed |
| IPv6 to a peer | denied |
| a peer that claims the container's address | rejected, both as a crafted packet and through a socket bound to the foreign address |
| a connection opened before the policy was loaded | cut |
| a reload | the policy is replaced atomically, without duplicates and without a gap |
| a broken ruleset | refused, and the loaded policy stays in place |
| a peer that forges the address *and* the MAC | reported as the boundary: it inherits the container's edges and is not detected |

Every denied destination is proven reachable *before* the policy is loaded,
so a later failure is the policy's doing and not a broken topology. The
harness never accepts a pass from an arbitrary error: a denied case has to
fail as a connection failure, and the same case has to have worked in the
baseline.

Run it on the target as root, with `nft` and `ip` on the path:

```
sudo python3 tests/check_container_isolation.py harness
```

`NFT_BINARY` and `IP_BINARY` override the binaries. The harness is not part
of `scripts/check`: it needs privileges and its own namespaces, so it is a
deliberate, candidate-only run.

## Release gates

These are the things that are not settled yet. Each one blocks the first
policy from being enabled.

- **The forging boundary has to be excluded.** The identity binds the
  address and the MAC. A peer that forges both is indistinguishable from the
  container at this layer; the harness reports that explicitly. Containment
  therefore requires that the bridge carries only trusted peers, or that the
  bridge enforces per-port MAC security. Until that is true for a candidate
  network, a policy must not be enforced.
- **Dependency categories are not enumerated yet.** The fleet's services
  depend on each other in categories, not in one flat list: indexer
  queries, metadata fetches, download client control, database access,
  media discovery, DNS, and public metadata or update endpoints. The
  categories are known from the modules; the exact edges inside them are
  not. Each edge has to be reviewed and listed before it can be approved.
  Until then, the catalogue stays empty. A blanket allow is not a
  substitute.
- **The observed edges are not reviewed.** The flow collector's edges for
  each candidate container have to be read, sorted into the categories
  above, and either approved one by one or recorded as intentional.
- **The candidate containers need a fixed identity and an explicit capability
  baseline.** A contained container needs a fixed `--ip`, a fixed
  `--mac-address` and `--cap-drop=ALL` plus only the capabilities its service
  needs. Today only FlareSolverr has a fixed address, and most containers do
  not drop ALL. Those changes belong to whoever owns each container's module,
  and the address has to come out of the network's subnet.
- **The network metadata has to be confirmed per host.** The policy unit
  checks the subnet at load time; the network's name, subnet and interface
  still have to be read once on the host before the first policy.
- **The kernel has to be checked.** The `inet` chains use connection
  tracking, which every Linux kernel has. The `bridge` chains use none for
  the approved edges; the ingress reply rule on the bridge does, so a policy
  with `ingress.enable` needs `nf_conntrack_bridge`. The harness proves it
  per target; without it the reply is dropped and the service fails closed,
  never open.

## Limits

- Containment limits what a container may reach. It is not a perimeter:
  Internet exposure stays behind Cloudflare Access and the host firewall,
  and the policy does not change that.
- The rules are keyed by the address and the MAC, not by a device. Two
  networks that reused one address would collide; the podman subnets are
  distinct, and the policy refuses an address outside the declared subnet.
- Containment governs the namespace the container runs in. It cannot govern a
  namespace the container is handed: a runtime socket mount (the podman
  socket) or a process handle it can ptrace lets it ask something else to act
  for it, and `SYS_ADMIN` would let it enter that namespace directly. The
  capability is refused for that reason. Socket mounts stay governed by the
  existing host control (`ghostship.security.socket_mount_allow`), which is
  outside this module.
- The default policy is egress containment. A container that serves inbound
  traffic needs the optional `ingress` block with its service ports, which
  also restricts what may reach it and needs connection tracking in the
  bridge family for the reply rule. It is off by default.
- A reload is atomic, but the policy is loaded before the container starts
  and stays loaded while it runs. There is no re-evaluation of the policy
  while a container is running, and no automatic reaction to a new
  observation.
