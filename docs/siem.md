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
| `ghostship-container-metrics` | native | per-container CPU, memory, PIDs, network bytes |
| Falco 0.45.1 + container plugin | native, modern eBPF | JSON alerts to the journal |

The SIEM network (`ghostsiem0`, 10.89.21.0/24) drops every connection its
containers open except DNS to their resolver (`inet ghostship_siem`). Images
are pinned by digest; update them in a PR. VictoriaLogs never deletes ingested
logs on request: its delete API is off.

## What is collected

- The whole journal: kernel audit records (AppArmor, the watch rules in
  `collection.nix`), sshd, systemd, firewall refusals (`refused connection:`),
  Podman events, Falco, and every container's output.
- Plex request lines (`logDebug=1`): client, port, network class (`WAN`,
  `LAN`, `Allowed Network (Subnet)`), method, path and auth state.
- Muximux nginx access and error logs.
- Not collected: qBittorrent's log (0600 to its app user; WebUI behind Access).

Secrets are removed before storage (`vector/redact.vrl`): token, key, password,
session and signature query parameters, bearer tokens and URL credentials.
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

## Tuning

- Falco: `siem/falco/ghostship_rules.yaml`. Exceptions only for investigated,
  legitimate workloads, as narrow as one container, process and path.
- Collection and parsing: `siem/vector/*.vrl`. Add a test case to
  `tests/siem-vector.toml` for each parser or redaction change.
- Never suppress events that match attack indicators: shell or downloader
  executions in app containers, credential reads, new listeners, unexpected
  egress, or requests resembling a published exploit. Investigate them.
