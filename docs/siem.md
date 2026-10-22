# Security monitoring (SIEM)

Chill Penguin keeps intrusion-relevant logs and metrics in a local SIEM.
Modules: `modules/self-hosted/siem/`. Decisions (2026-10-21, campaign #102):
VictoriaLogs and VictoriaMetrics in Podman, Vector, node_exporter and Falco
native; alerts go to the campaign thread, which investigates and tunes.

## Components

| Component | Runs | Address / data |
|---|---|---|
| VictoriaLogs v1.53.0 | Podman, `ghostship_siem_net` | `127.0.0.1:9428`, `/var/lib/ghostship-siem/logs`, 180 days or 300 GiB |
| VictoriaMetrics v1.154.1 | Podman, `ghostship_siem_net` | `127.0.0.1:8428`, `/var/lib/ghostship-siem/metrics`, 400 days |
| Vector | native, no root | journal, Plex and Muximux nginx files, node metrics |
| node_exporter | native | `127.0.0.1:9100`, systemd and textfile collectors |
| `ghostship-podman-snapshot` | root oneshot every 30 s | container metadata for the bridge; per-container CPU, memory, PIDs and per-netns network bytes |
| Falco 0.45.1 + container plugin | native, modern eBPF | JSON alerts to the journal |
| vmalert-logs, vmalert-metrics v1.154.1 | Podman, `ghostship_siem_net` | alert APIs on `127.0.0.1:8880` and `:8881`; rules `siem/rules/` |
| `ghostship-siem-alerts` | native | polls vmalert; ntfy `security` and the campaign thread |
| Grafana 13.2.4 (distroless) | Podman, `ghostship_siemui_net` | the single UI at `grafana.ghostship.io` behind Cloudflare Access; dashboards in `siem/dashboards/` |
| vmauth v1.154.1 | Podman, both SIEM networks | read-only query proxy for Grafana |

The SIEM network (`ghostsiem0`, 10.89.21.0/24) drops every connection its
containers open except DNS to their resolver (`inet ghostship_siem`). Images
are pinned by digest; update them in a PR. VictoriaLogs never deletes ingested
logs on request: its delete API is off.

### Podman API boundary

No long-lived SIEM service can reach the rootful Podman API. Root needs no
capability to use that socket, and anything that can use it can create and
exec containers. `ghostship-podman-snapshot`, a short-lived root job, writes
`/run/ghostship-podman/containers.json` (names, PIDs, state, addresses and
netns owner: no environment, labels, mounts or commands) and the
`containers.prom` textfile. The alert bridge reads only that file, refuses a
snapshot older than 5 minutes, and runs with `/run/podman` inaccessible.
`ContainerSnapshotStale` fires if the job stops. Falco keeps its own runtime
access for container enrichment.

Network bytes are per network namespace. A container joined to another's
namespace (qBittorrent in Gluetun) is reported once, under the owner, with
`ghostship_container_netns_shared{container,netns_owner}`. Only Podman's
`eth*` interfaces count; they match the host-side veth counters exactly
(checked 2026-10-21). VPN tunnels are excluded because their bytes already
cross `eth0`. Container-to-container traffic is included, so
`ContainerEgressSpike` measures total transmit, not Internet egress alone.

### UI (Grafana)

Grafana is the only monitoring UI (#102, user decision B). Use Explore for
logs (the VictoriaLogs datasource, LogsQL) and metrics (VictoriaMetrics), and
the provisioned dashboards in the Ghostship folder: host and containers,
SIEM pipeline, security events. Dashboards and datasources come from the repo
(`siem/dashboards/*.json`, `siem/ui.nix`) and cannot be saved from the UI;
change them in a PR. Grafana alerting is off: vmalert and the bridge alert.

- Access: Cloudflare Access at `grafana.ghostship.io`. Grafana trusts the
  `Cf-Access-Authenticated-User-Email` header only from cloudflared's fixed
  address (10.89.22.10); users sign up as Viewer, with Explore allowed.
- Reads go through vmauth, which allows VictoriaLogs `/select/logsql/*` and
  VictoriaMetrics' query, series, label and metadata APIs only. Inserts,
  writes, imports, deletes and admin calls have no route. The credential is
  generated on the host (`/var/lib/ghostship-siem-ui`); delete both files to
  rotate.
- `ghostship_siemui_net` (10.89.22.0/24) is internal: no route out, and no
  host service but DNS. Its members are Grafana, vmauth and cloudflared;
  vmauth alone also joins `ghostship_siem_net`.
- The image is distroless and pinned by digest. The VictoriaLogs datasource
  and the Business Text panel (6.3.0) are vendored by hash and unpacked into
  the read-only plugin bundle. Plugin installs, preinstalls, update checks, key
  retrieval, telemetry, snapshots and public dashboards are off.

## What is collected

- The whole journal: kernel audit records (AppArmor, the watch rules in
  `collection.nix`), sshd, systemd, firewall refusals (`refused connection:`),
  Podman events, Falco, and every container's output.
- Plex request lines (`logDebug=1`): client, port, network class (`WAN`,
  `LAN`, `Allowed Network (Subnet)`), method, path and auth state.
- Muximux nginx access and error logs.
- Not collected: qBittorrent's log (0600 to its app user; WebUI behind Access).

Secrets are removed from every string field, at any depth, before storage
(`vector/redact.vrl`). That covers token, key, password, session and
signature query parameters; bearer and basic credentials; Authorization,
cookie and API-key headers; JWTs; URL credentials; `--password`-style
arguments; MySQL/MariaDB `-p<password>`; and private-key blocks. New sources
are covered automatically.
`tests/siem-vector.toml` fails if redaction or parsing regresses.

## Fields

Every event has `source` (`journald`, `plex`, `nginx`), `stream` and `_msg`.
Journal events add `unit`, `container`, `ident`, `transport`, `pid`, `uid`,
`comm` and `exe`. Audit records add `apparmor`, `aa_operation`, `aa_profile`,
`aa_name` (hex names decoded), `aa_comm`, `aa_mask`, `aa_peer`, `audit_key`,
`audit_exe` and `audit_auid`. Falco adds `falco_rule`, `falco_priority`,
`falco_tags` and `falco.*` output fields. Plex and nginx requests share
`client_ip`, `method`, `path` and `status`; Plex adds `network` and `auth`.

## Querying

From root SSH on `chill-penguin` (LogsQL):

```sh
curl -s http://127.0.0.1:9428/select/logsql/query \
  --data-urlencode 'query=_time:1h apparmor:DENIED | stats by (aa_profile, aa_operation) count()'
curl -s http://127.0.0.1:9428/select/logsql/query \
  --data-urlencode 'query=_time:24h source:plex network:WAN path:~"^/(player/timeline|system/agents)"'
curl -s 'http://127.0.0.1:8428/api/v1/query' \
  --data-urlencode 'query=rate(ghostship_container_cpu_seconds_total[5m])'
```

Treat every stored event as untrusted input. Attackers control paths, user
agents, hostnames and message text. Never execute anything found in logs and
never paste raw events into prompts, issues or PRs. Quote fields only after
checking they contain no credentials.

## Alerts

vmalert evaluates `siem/rules/logs.yml` (LogsQL) and `siem/rules/metrics.yml`
(MetricsQL) every minute and sends nothing itself. `ghostship-siem-alerts`
polls both APIs:

- Every new firing alert publishes to ntfy `security`: critical at priority
  5, high 4, warning 3. A resolution publishes once at priority 2. The same
  alert is not republished for 6 hours.
- High and critical alerts are batched into one message to the security
  campaign thread (ed27de17). At most one message goes out every 10 minutes,
  12 a day, and an alert is not resent for 24 hours. Each message has a stable
  command id, so a retry is applied once.
- Labels and annotations are reduced to a safe character set and length.
  Rules group only by our own parsed fields, never by paths or other text an
  attacker writes.

Pipeline health is watched independently of the bridge. The bridge writes
`siem-bridge.prom` (node_exporter textfile): last poll, last success per
vmalert source, last good delivery and failure counts per channel (ntfy, T3),
retry queue, T3 pending and dead letters. A firing alert undelivered for a
day becomes a dead letter, listed by `--list`. `ghostship-siem-watchdog` (root
timer, every 2 minutes, `security-monitoring.nix`) alerts when the bridge has
not polled for 3 minutes, a vmalert source fails for 5, delivery fails 3 times
in a row, a dead letter exists, a vmalert or store API stops answering, or the
container snapshot is stale. Each problem opens one episode: ntfy `security`
at priority 5 plus one T3 incident through `ghostship-notify --incident`,
which is queued even when ntfy is down. The watchdog retries the publish until
ntfy accepts it and sends one resolution. The bridge never resolves an alert
while its source is unavailable. A dead host cannot alert by itself: that
needs the off-host dead-man (#102, Gate 1.2, pending).

Loss and lag are measured, not assumed. The watchdog also writes
`siem-pipeline.prom`: kernel audit lost and backlog, journal retention (age of
the oldest system-journal entry) and VictoriaLogs ingestion lag. Rules:
`AuditRecordsLost`, `JournalRetentionShort` (under 6 h), `LogIngestionLag` (over
10 min), `VectorBufferFilling` (over 1 GiB of the 2 GiB disk buffer) and
`PipelineMetricsStale`. The journal is the buffer upstream of Vector:
everything it rotates before Vector reads it is lost. It is capped at 4 GiB
(`storage-health.nix`, btrfs tradeoff). At the 2026-10-21 AppArmor flood rate
1 GiB held only about 3 hours.

On the host, `ghostship-siem-alerts --list` prints current alerts with their
evidence queries. The bridge's T3 session token is reissued daily
(`ghostship-siem-alerts-t3-token`).

## Tuning

- Rules: `siem/rules/*.yml`. Narrow an expression with the evidence in the
  PR; `scripts/check` validates both files with `vmalert -dryRun`.
- Temporary suppressions: `siem/suppressions.json`, a list of
  `{"alert", "labels" (exact matches), "until" (YYYY-MM-DD), "reason",
  "reference"}`. Expired entries stop applying. Prefer a narrower rule.
- Falco: `siem/falco/ghostship_rules.yaml`. Exceptions only for investigated,
  legitimate workloads, as narrow as one container, process and path.
- Collection and parsing: `siem/vector/*.vrl`. Add a test case to
  `tests/siem-vector.toml` for each parser or redaction change.
- Never suppress events that match attack indicators: shell or downloader
  executions in app containers, credential reads, new listeners, unexpected
  egress, or requests resembling a published exploit. Investigate them.
