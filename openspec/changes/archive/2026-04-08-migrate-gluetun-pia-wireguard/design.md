## Context

The current Gluetun module on `chill-penguin` is pinned to PIA over OpenVPN
with `SERVER_REGIONS = "CA Vancouver"` and `VPN_PORT_FORWARDING = "on"`.
qBittorrent and NZBGet run in Gluetun's network namespace, and qBittorrent's
listen port is already reconciled from Gluetun's port-forwarding events and a
host-side monitor loop. This arrangement is functional but too slow for the
user's workload.

Upstream Gluetun still does not expose native PIA WireGuard provider support,
but it does support WireGuard through the custom-provider path and continues to
support PIA-backed VPN-side port forwarding by using PIA credentials,
`SERVER_NAMES`, and the persisted `/gluetun` storage directory. PIA's live
server inventory exposes port-forward-capable regions and WireGuard server
metadata, which makes it feasible to select a fast eligible region
automatically instead of pinning the system to one hard-coded OpenVPN region.

The user also wants the "fastest server" decision to be refreshed periodically
instead of only during restarts. That means the design needs two layers:

- a daily selector that can do heavier probing and a tiny bounded throughput
  test
- a lightweight startup bootstrap that consumes the cached winner and starts
  Gluetun quickly

This change affects the `chill-penguin` server host, the Gluetun container's
startup contract, qBittorrent port reconciliation, and operational monitoring.
It does not change the broad service topology where qBittorrent and NZBGet stay
behind Gluetun in the shared container network namespace.

## Goals / Non-Goals

**Goals:**
- Replace the current PIA OpenVPN setup with a PIA WireGuard custom-provider
  startup flow.
- Maintain a daily-refreshed preferred PIA WireGuard endpoint chosen from live
  PF-capable server metadata.
- Keep Gluetun restart time reasonably fast by using cached selector output at
  startup instead of doing the full benchmark loop every restart.
- Preserve VPN-side port forwarding and keep qBittorrent synchronized with the
  forwarded port.
- Keep `/srv/apps/gluetun:/gluetun` persistent so PIA's forwarded-port lease
  and Gluetun state survive container replacement.
- Expand monitoring so operators can see the difference between Gluetun being
  down, the VPN path being unhealthy, and port forwarding being absent or out
  of sync.
- Document the new runtime inputs and validation path.

**Non-Goals:**
- Changing NZBGet to use VPN-side port forwarding; it only needs the shared
  tunnel path.
- Replacing Gluetun with a custom standalone PIA client.
- Hard-pinning a single PIA WireGuard region in repo config.
- Running a continuous speed-test daemon throughout the day.

## Decisions

### Decision: Use Gluetun's custom-provider WireGuard path instead of waiting for native PIA WireGuard support

The repo will keep Gluetun as the VPN runtime and will feed it dynamically
generated custom-provider WireGuard settings for PIA.

Why:
- Native PIA WireGuard support in Gluetun is still not the supported path.
- The existing stack already depends on Gluetun's firewalling, control server,
  port-forward hooks, and shared network namespace.
- This minimizes blast radius compared with replacing the VPN runtime entirely.

Alternatives considered:
- Stay on OpenVPN and only change regions. Rejected because the user's goal is
  to move to WireGuard for better throughput, and static region selection is
  part of the existing problem.
- Replace Gluetun with a separate PIA-only WireGuard container. Rejected
  because it would reimplement functionality the stack already relies on.

### Decision: Separate server selection from startup bootstrap

The host will run a selector service and timer once per day to compute the
preferred PF-capable WireGuard target, while Gluetun startup will consume the
last cached selector result.

Why:
- The user explicitly asked for periodic reselection, not a one-time static
  choice.
- Daily selection allows a heavier probe including a tiny download-based test.
- Startup remains predictable and does not have to benchmark the world on every
  container restart.

Alternatives considered:
- Select a region only on startup. Rejected because it misses the user's daily
  refresh requirement.
- Rebenchmark continuously. Rejected because it adds noise, churn, and
  unnecessary traffic.

### Decision: Filter candidates to PF-capable WireGuard servers first, then do a two-phase benchmark

Candidate selection will start from PIA's live inventory, restrict to regions
with port forwarding and WireGuard metadata, then use a fast latency/connect
pass to narrow the set before a short bounded download test picks the final
winner.

Why:
- Port forwarding is a hard requirement.
- A raw "fastest ping" choice may not correlate well enough with actual
  download performance.
- A bounded second-phase download test is enough to distinguish near-ties
  without turning the selector into a bandwidth hog.

Alternatives considered:
- Probe all servers with full download tests. Rejected because it is wasteful.
- Use only latency. Rejected because the user explicitly asked to see if
  something can be downloaded from each server for a quick speed test.

### Decision: Keep Gluetun as the owner of the forwarded-port lease and qBittorrent sync hooks

The host bootstrap will only prepare the connection inputs. Gluetun will remain
the component that obtains and refreshes the forwarded port, while the existing
up/down command pattern continues to push the active port into qBittorrent.

Why:
- Gluetun already has the PIA port-forwarding lifecycle integration.
- Reimplementing forwarded-port renewal outside Gluetun would duplicate logic
  and increase failure modes.
- qBittorrent port synchronization is already present and can be improved
  rather than replaced.

Alternatives considered:
- Move PIA PF renewal into a separate custom daemon. Rejected because it would
  split ownership of the same runtime state across components.

### Decision: Upgrade monitoring from OpenVPN-specific and liveness-only checks to generic VPN plus PF health

Monitoring will move to Gluetun's generic port-forwarding control endpoint and
should treat missing forwarded-port state as a first-class failure mode.

Why:
- The current monitor still reads the old OpenVPN-specific control route.
- WireGuard migration should not depend on an OpenVPN-named endpoint.
- Operators need to know whether the problem is container liveness, VPN health,
  or PF drift.

Alternatives considered:
- Keep the current monitor mostly unchanged. Rejected because it encodes stale
  assumptions and misses a key migration risk.

## Risks / Trade-offs

- [PIA inventory or manual-connection APIs can change and break the selector or bootstrap]
  -> Mitigation: keep the selector and startup scripts explicit, log-rich, and
  fail fast when discovery or token exchange breaks.
- [The quick daily speed test can pick a temporarily "lucky" server]
  -> Mitigation: keep the benchmark short but multi-stage, and preserve the
  last known good winner until a new candidate is fully prepared.
- [The chosen winner can degrade between daily runs]
  -> Mitigation: retain restart-driven health recovery and allow Gluetun to
  keep using the cached winner until the next selector cycle or operator
  intervention.
- [Port forwarding can silently disappear while the tunnel remains up]
  -> Mitigation: monitor forwarded-port state directly and trigger
  reconciliation or restart when it vanishes or no longer matches qBittorrent.
- [New secrets and runtime generation logic increase operational complexity]
  -> Mitigation: document the required inputs and keep all generated runtime
  files ephemeral and host-owned.

## Migration Plan

1. Add a selector helper and timer that:
   - reads PIA credentials and any constraints from secrets
   - fetches the live PIA server inventory
   - filters for PF-capable WireGuard regions
   - runs a fast latency/connect pass
   - runs a short bounded download probe against the best few candidates
   - writes the preferred winner and fallback metadata to cached runtime state
2. Add a startup bootstrap helper that consumes the cached winner, performs the
   PIA WireGuard bootstrap, and writes the runtime inputs Gluetun needs.
3. Update `modules/self-hosted/gluetun.nix` to use that startup/bootstrap flow
   and the custom-provider WireGuard runtime path instead of the current native
   PIA OpenVPN configuration.
4. Preserve and adapt the port-forwarding hooks and monitor to work through the
   generic Gluetun control endpoints.
5. Update docs and secrets guidance.
6. Build the target host configuration with:
   ```fish
   nixos-rebuild build --flake .#chill-penguin -L
   ```
7. Activate with:
   ```fish
   ./result/bin/switch-to-configuration switch
   ```
8. Verify:
   - the selector writes a preferred PF-capable WireGuard target
   - Gluetun connects using the cached winner
   - public IP changes from the WAN IP
   - a forwarded port is present and non-zero
   - qBittorrent's listen port matches the forwarded port
   - qBittorrent/VueTorrent still updates from Gluetun port-forwarding events
   - Gluetun and dependent containers recover after a forced restart

Rollback:
- Restore the previous OpenVPN-based Gluetun configuration from Git, rebuild,
  and switch back to the earlier generation.
- Keep `/srv/apps/gluetun` intact unless it is proven to contain stale state
  that blocks the old runtime from reconnecting.

## Open Questions

- Which bounded download probe is the best balance of realism and low churn:
  a small HTTP fetch from the candidate endpoint path, or a PIA-specific
  connection/bootstrap transfer metric if exposed by the API?
- Whether the selector should keep a small ranked fallback list so Gluetun
  startup can fail over locally if the daily winner goes bad before the next
  timer run.
