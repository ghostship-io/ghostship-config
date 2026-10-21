# Changelog

## [3.17.1] - 2026-10-21

- SIEM alerts reach ntfy. `ghostship-notify` found ntfy by running `podman inspect`, which fails in the bridge's capability-free sandbox. Since #156 every ntfy publish from the bridge failed; T3 delivery was unaffected. The bridge now resolves ntfy through the Podman API socket and passes `GHOSTSHIP_NOTIFY_URL`.
- A failed ntfy publish is retried on the next poll. Previously it was recorded as sent and stayed quiet for the 6-hour renotify window.

## [3.17.0] - 2026-10-21

- SIEM part 2: detections and alerting (docs/siem.md).
  - Two vmalert v1.154.1 containers evaluate `siem/rules/logs.yml` (LogsQL) and `siem/rules/metrics.yml` (MetricsQL), with no notifier of their own. They share one strict complain-mode AppArmor profile; the registry gains a `source` option for shared profile files.
  - Log detections:
    - AppArmor denials in Plex's enforced domains;
    - shells, downloaders and interpreters executed by app server domains;
    - Falco critical and warning alerts;
    - Plex2Shell-surface requests from the WAN, and Plex preference writes;
    - exploit patterns against Muximux;
    - SSH authentication-failure bursts and firewall refusal bursts;
    - sensitive file changes outside NixOS activation;
    - kernel module loads, kexec and ptrace attaches;
    - silent journal or Plex ingestion.
  - Metric detections: sustained container CPU (miners), container egress spikes (proxies, exfiltration), SIEM components down, stale host or container metrics, Vector errors, low disk.
  - `ghostship-siem-alerts` polls vmalert on loopback. It publishes new and resolved alerts to ntfy `security`, and batches high and critical alerts into one message to the security campaign thread: at most one every 10 minutes and 12 a day, with a stable command id. Labels are sanitized, and the message frames alert text as untrusted data. `--list` shows current alerts. Its own T3 session token is issued daily.
  - NixOS activation's store Perl reading `/etc/shadow` and rewriting `/etc` is excluded, narrowly, from the Falco and audit detections. It was seen on every deployment today.
  - `scripts/check` validates both rule files with `vmalert -dryRun` and runs the bridge's tests (sanitizing, dedupe, resolution, rate limits, suppression expiry).
  - Falco, Vector, node_exporter and the SIEM network units now report failures through `ghostship-failure@`.

## [3.16.2] - 2026-10-21

- SIEM container metrics move to `/var/lib/ghostship-container-metrics`. node_exporter could not traverse the root-only `/var/lib/ghostship-siem` (`node_textfile_scrape_error 1`), so the counters written there never reached VictoriaMetrics.

## [3.16.1] - 2026-10-21

- SIEM container metrics read the Podman REST API over its socket. `podman ps` failed under the collector's read-only sandbox (it takes lock files), so no per-container counters reached VictoriaMetrics after #153.
- Falco alerts carry the container plugin's fields (container id, name, image) again (`append_output`); the minimal configuration had dropped them.

## [3.16.0] - 2026-10-21

- Security monitoring (SIEM), part 1: collection and storage (docs/siem.md).
  - VictoriaLogs v1.53.0 and VictoriaMetrics v1.154.1 run in Podman, pinned by digest, on their own network (`ghostship_siem_net`). Every connection they open is dropped except DNS, and their ports are published on 127.0.0.1 only. Each has a strict complain-mode AppArmor profile, a read-only image, no capabilities and noexec storage. nixpkgs' VictoriaLogs 1.52.0 can panic or drop logs, so it is not used.
  - Vector (native, no root) ships the whole journal, Plex's log and Muximux's nginx logs. It parses AppArmor and audit fields, Falco alerts and Plex and nginx requests, and redacts tokens, keys, passwords and URL credentials before storage. `tests/siem-vector.toml` runs in `scripts/check` and fails if redaction or parsing regresses.
  - node_exporter and a per-container counter service (CPU, memory, processes, network bytes) feed VictoriaMetrics, so a cryptominer or proxy shows up in the numbers.
  - Falco 0.45.1 runs natively on the modern eBPF probe, with the container plugin, packaged from the upstream release with pinned hashes. A trial on the host flagged a planted `/etc/shadow` read in a container.
- New intrusion-relevant log sources:
  - Audit rules watch identity files, sudoers, SSH configuration and keys, runtime systemd units, the system profile, kernel module loads, kexec and ptrace attaches.
  - The firewall logs refused connections.
  - Plex logs every request with the client and its network class (`logDebug`; Plex strips tokens).
  - The audit backlog rises from 1024 to 8192, matching auditd.

## [3.15.175] - 2026-10-21

- Plex2Shell (CVE-2026-96652/4/5/6, exploited since 2026-10-17): Plex already ran 1.43.5.11029, past the 1.43.3.10861 fix, with no indicators of compromise. Its Internet-facing AppArmor domains (server, interpreter, ldconfig) now **enforce**; startup and the healthcheck keep learning.
  - The interpreter rules were pinned to the 1.43.4 `Plug-ins-e5521bd8c` directory and would have blocked every metadata agent on 1.43.5. The build hash is now a glob, and the shipped agents' code and per-identifier state are allowed.
  - The server may not write or link into the allowlisted codec sets, the step Plex2Shell used to load its payload.
  - Observed benign server reads are allowed: DMI board names, `/proc/*/cmdline`, interface and route tables, CPU frequency limits, the bundled library directory and `/dev/shm` links.
  - The AppArmor collector checks each label's own mode (`apparmorProcessModes`), so a domain loaded in the wrong mode is reported.
- eMudhra intermediate key compromise: the host distrusts emSign ECC Root CA - G3 and Comodo AAA Services root (`security.pki.caCertificateBlacklist`). Every third-party container gets the host bundle and blanked copies of both roots, `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`; the Node images use OpenSSL's store, and Plex's bundled `cacert.pem` is replaced. Throwaway copies of the Plex, Sonarr, Bazarr and Uptime Kuma images rejected the compromised test chains with these mounts and still reached plex.tv. Host services in the private integrations use the host bundle.

## [3.15.174] - 2026-10-21

- The read-only images without s6 also get a noexec `/run`: Chaptarr, cloudflared, the Grimmory database, Homepage, ntfy, Plex Auto Languages, Recyclarr, Seerr and Uptime Kuma. Throwaway copies of each image started cleanly with it. Their whole filesystem now has no writable, executable path.
- Plex Auto Languages' image-declared `/logs` anonymous volume is replaced by a noexec host directory.

## [3.15.173] - 2026-10-21

- AppArmor learning noise, from the largest live complain-mode sources: Sway's keymap reads of `xkeyboard-config-2` (about 9k a minute), RomM Valkey reading its own `/proc/<pid>/stat`, FlareSolverr's healthcheck curl starting from the top profile, and Gluetun's healthcheck loading the system CA roots. Each rule is limited to the observed path.

## [3.15.172] - 2026-10-21

- AppArmor: the agent desktop's top profile may run `s6-envuidgid`. Every s6 service that drops to `abc` runs `s6-setuidgid`, which calls `s6-envuidgid`. Without the rule, the LXQt desktop, D-Bus, PulseAudio, Selkies, Pelorus and the Chrome idle reaper all ran in ruleless `null-*` learning profiles. That logged about 175k audit records a minute, rotated auditd's logs in minutes and crowded the rest of the journal out. The same rule is added to the other LinuxServer profiles that allow `s6-applyuidgid`.

## [3.15.171] - 2026-10-20

- Agent viewer: one launcher. **Apps** has a tile for Chrome · Personal, Chrome · Agent, OrcaSlicer and Blender (from `apps.json`), and **Open** lists everything running. The mode switch reads **Apps | Desktop**.
- **×** closes at once without a confirmation: the tab disappears immediately, and an app is asked to quit every 2 s (so a dialog on top cannot hold it open) and stopped after 10 s. Agents' `close` still never discards unsaved work without `--force`.
- Blender 5.0 is installed and launches in its own app session.

## [3.15.170] - 2026-10-20

- Agent desktop: desktop app sessions. OrcaSlicer (and later other catalog apps, `apps.json`) runs on its own headless Sway screen with its own pointer and keyboard, opened from the viewer's new **Apps** launcher or by agents through `ghostship-gui app` (ghostship-agent 0.30.0). Each session is a viewer tab with a live view; touch pauses agent input, and closing never discards unsaved work without force. A 10,000+-keystroke concurrency gate across two sessions had zero cross-talk. Orca works again: the image now has WebKitGTK 4.1, and GTK image loading no longer aborts in the container (bwrap stand-in).
- Pin ghostship-agent 0.30.0: `ghostship-gui app` drives app sessions.
- `desktop.ghostship.io` serves the viewer at the root (no redirect); Selkies moved to `/desktop/` and the old `/agents/` address redirects to `/`. The main page groups **Apps** and **Browser sessions**; the health check and the update service's viewer gate follow the new paths.

## [3.15.169] - 2026-10-20

- Gluetun keeps a writable image filesystem. It creates its user in `/etc/passwd` at every start, so with `--read-only` (#145) it failed with "read-only file system", and qBittorrent, which shares its network, went down with it.

## [3.15.168] - 2026-10-20

- 17 containers run with a read-only image filesystem (`--read-only`), so a compromise cannot replace image binaries or plant code in the image: Bazarr, Chaptarr, cloudflared, Gluetun, the Grimmory database, Homepage, ntfy, NZBGet, Plex Auto Languages, Prowlarr, Radarr, Recyclarr, the RomM database, Seerr, Sonarr, Tautulli and Uptime Kuma.
  - **Selection:** each container's overlay upper layer showed it writes only Podman's passwd/group entries and its mount points.
  - **Testing:** throwaway read-only copies of eight images started cleanly.
  - **Still writable, with the reason** (recorded in `container-hardening.nix`):
    - FlareSolverr patches `/app/chromedriver`.
    - Muximux, pyLoad and qBittorrent run root init.
    - Tdarr writes `/app` assets.
    - Grimmory's root entrypoint rewrites `/etc/passwd`.
    - RomM templates `/etc/nginx/conf.d`.

## [3.15.167] - 2026-10-20

- Fixed the outage from #143. LinuxServer images started as the app user (Sonarr, Radarr, Prowlarr, Bazarr, NZBGet, Tautulli and the RomM database) run s6 preinit through the setuid-root `s6-overlay-suexec`. With every capability dropped it failed with "unable to setgid to root", and those containers (and RomM, which depends on its database) crash-looped. They now keep the LinuxServer startup set: chown, dac_override, fowner, kill, setgid, setuid.

## [3.15.166] - 2026-10-20

- Kernel-enforced execution limits for containers (`container-hardening.nix`), so a compromised app can't run code it writes. AppArmor is still learning in complain mode and blocks nothing.
  - **Data volumes:** every writable data volume is mounted `noexec,nosuid,nodev`. That covers configs, media, downloads, databases and state for all containers except Plex, the agent desktop and T3.
  - **Temporary storage:** `/tmp` and `/var/tmp` are size-capped `noexec,nosuid,nodev` tmpfs. RomM gets a disk-backed noexec `/tmp` for multi-GB uploads. Grimmory keeps an executable `/tmp` because pdfium4j maps `libpdfium.so` from there.
  - **Capabilities:** every container drops ALL and adds back only what its strict profile lists. Most get none; root-started LinuxServer images keep chown, dac_override, fowner, kill, setgid and setuid; Gluetun keeps net_admin and net_bind_service. So a setuid binary in an image can't regain capabilities.
  - **Why the exceptions:** a live scan found code executing from writable paths only in Plex's downloaded codecs, Grimmory's `/tmp` pdfium and the agent desktop's OrcaSlicer. Plex and the agent desktop follow separately.
  - **Impact:** NZBGet's `/scripts` is now noexec. No extension is configured; enabling one later needs an explicit exception.

## [3.15.165] - 2026-10-20

- Agent desktop AppArmor: the Chrome launchers may execute `with-contenv`, `s6-envuidgid`, `s6-applyuidgid`, and the root-owned `run-chrome`, `chrome-close` and `ghostship-chrome-instance` scripts. Before, these were read-only, so agent Chrome and its subtree ran in ruleless `null-*` learning profiles (about 100k events a minute).

## [3.15.164] - 2026-10-20

- AppArmor fixes from the first deploy of the strict profiles (#140). In complain mode an exec with no matching rule enters an empty `null-<path>` learning profile, and its whole subtree then runs ruleless.
  - Inside a child profile, `cx -> name` names a child of that child, not a sibling. So FlareSolverr's and Tdarr's sibling transitions now use `px -> ghostship-<container>//<name>`.
  - Tdarr's startup gets `s6-envuidgid`.
  - Grimmory's JVM may re-exec `java`.

## [3.15.163] - 2026-10-20

- Every container except T3 now has its own strict AppArmor profile in complain mode (user direction: no broad policy).
  - Covered: the arrs, downloaders, Gluetun, cloudflared, the web apps, the databases, Tdarr, FlareSolverr, the internal services and the agent desktop.
  - Each profile lists exact executables, libraries, data paths, network families and capabilities, with child profiles for daemons, interpreters, helpers and healthchecks. Policies live in `modules/self-hosted/apparmor/<container>.profile`.
  - The agent desktop is split into per-process children (Chrome per identity, Sway, sshd, Selkies, Pelorus, API, agent shells). The viewer profile is unchanged.
- `ghostship-container-default` now grants nothing and logs everything. Only ad-hoc job containers use it. An assertion requires every declared container except T3 to have its own profile.
- `ghostship-apparmor-review` tracks every container. Each app declares the labels it expects (`apparmorProcessProfiles`, `apparmorRequiredProcessProfiles`). Images without `cat` give the audit heartbeat their own reader (`apparmorHeartbeat`).
- `ghostship-apparmor-review` reads the journal once per collection, not once per container, with a 10-minute bound.
- The kernel audit backlog is raised to 8192 records (`ghostship-audit-backlog`), so complain-mode bursts at container start aren't dropped. Dropped records would reset every learning window.
- Containers running with no_new_privs (GitHub coordinator, private integrations) get flat profiles. Under no_new_privs AppArmor never enters child profiles; complain mode logs "no new privs", and enforce mode would refuse the exec.
- Documented that a reloaded policy reaches an idle task only at its next mediated call. This is why Plex's `ptrace readby` events continue until Plex restarts.

## [3.15.162] - 2026-10-20

- Agent viewer: closing a session also closes tabs and popups the agent opened while the close waited for its in-flight call, and a manual scroll of the session strip no longer snaps back on each refresh (Codex review of #138).

## [3.15.161] - 2026-10-20

- Agent viewer: every open session is a tab along the top (identity dot, label, × to close) instead of ‹ › stepping, and **+** opens a Personal or Agent window from there. Closing pauses the session, waits for an in-flight agent call, then closes its tabs (home last) and removes its registry entry; closing an agent's session asks first. Cards in the grid have a Close button too.

## [3.15.160] - 2026-10-20

- Agent viewer: the address bar accepts a bare host such as `amazon.com` (it was a `type=url` field, so the browser demanded a scheme before the viewer could add `https://`).

## [3.15.159] - 2026-10-20

- Agent desktop: one web UI. `desktop.ghostship.io` opens the viewer with a **Browsers | Desktop** switch; Desktop mode embeds Selkies, which nginx still serves at `/` to frames and health checks, and leaving it ends the stream. nginx redirects are now relative: `/agents` no longer redirects to `http://desktop.ghostship.io:3000/agents/`.

## [3.15.158] - 2026-10-20

- Every AppArmor profile now runs in complain (learning) mode: `ghostship-container-default` (the 25 containers without their own profile), `ghostship-agent-desktop` and `ghostship-desktop-viewer` move from enforce. Explicit `deny` rules still apply in complain mode, so Podman's baseline denials (mount, `/proc` and `/sys` writes, kernel security files) and the viewer's denials of Chrome profiles, SSH keys and container secrets stay in force. Per-service strict profiles replace the shared default next (#102).

## [3.15.157] - 2026-10-20

- Agent viewer: **+ Personal** / **+ Agent** start an idle-stopped Chrome (through `chrome-ensure`) instead of failing with "browser stopped". The viewer's AppArmor profile may run only `chrome-ensure`, under the container profile with a scrubbed environment.

## [3.15.156] - 2026-10-20

- `ghostship-apparmor-review` identifies a policy by its own file's content hash, not by its path in the combined `apparmor.d` tree. Adding the agent-desktop profile (#130) renamed that tree, so every other profile reported `configuration-mismatch`, and the next collection would have reset their learning windows despite byte-identical policies. Includes are embedded by content-addressed store path, so real include changes still count. Plex's process labels now allow `ghostship-plex//healthcheck`, so a scan that coincides with a healthcheck no longer fails `process-profile-mismatch`.

## [3.15.155] - 2026-10-20

- Agent desktop: BladeBro 4.2.2 -> 4.6.4 (canary-tested by ghostship-agent-desktop-update).

## [3.15.154] - 2026-10-20

- Fixed `ghostship-agent-desktop-update` canaries: the update service now uses the host's configured podman. The plain package refused the canary's AppArmor profile ("AppArmor is not enabled"), so every candidate failed before testing.

## [3.15.153] - 2026-10-20

- Pin ghostship-agent 0.29.0: browser agents drive their own windows in the browser stages without the desktop input lock or tab activation, publish run records (label, harness, model, T3 thread) for the agent viewer, and stop on `paused` when a person takes over a window.

## [3.15.152] - 2026-10-20

- Concurrent agents on one signed-in Chrome. Each identity's Chrome now runs in its own browser stage: a Sway compositor with a virtual 1920x1080 output, virtual mouse and keyboard, and no automatic focus changes. Agents drive their own windows with target-scoped input, never stealing focus from each other or from a person on the desktop. Measured: 30,000+ barrier-synchronised ops at 8 and 16 agents, and a 2 h soak, with zero cross-talk. Browser fingerprint, CDP detection and bot-check results match the previous desktop. Logins stay in one authoritative profile per identity, with no replication.
- Agent viewer at `https://desktop.ghostship.io/agents/`: mobile-first cards per agent window (label, identity, harness/model, T3 thread, current action, live preview). Tapping a card opens that agent's live view; any touch pauses only that agent (`bladebro-gate` refuses its page-changing calls) until Resume. It verifies the Cloudflare Access token on every request and runs under a new enforce-mode AppArmor profile (`ghostship-desktop-viewer`). The desktop now resizes to the client's screen.
- Browser sessions survive restarts: Chrome is closed through DevTools before the container stops (it previously lost cookies written in its last ~30 s).
- Automatic desktop updates: `ghostship-agent-desktop-update` gates signed Chrome stable, checksummed Bladebro and the webtop digest in lab canaries (concurrency, CDP detection, bot checks, fingerprint parity, profile compatibility on network-less snapshot copies). It then commits `containers/agent-desktop/versions.json`, drains, snapshots, deploys and verifies, rolling back with profile restore on failure, and reports to NTFY. Retailer sites are never part of automated tests.

## [3.15.153] - 2026-10-20

- Stop the inference scheduler by signalling its container process and waiting for the scheduler and its Podman attachment to exit. Orderly configuration switches no longer kill the attachment and report a false service failure; genuine nonzero scheduler exits still fail. Shutdown uses pinned process identities and leaves unrelated container processes alone.

## [3.15.152] - 2026-10-20

- Allow the private integrations container 110 seconds to stop, covering its supervisor's 100-second worker drain and descendant reaping. Allow systemd 130 seconds for the stop and cleanup. Podman's default 10-second timeout could kill the supervisor during a deployment and report exit 137.

## [3.15.151] - 2026-10-20

- Pin ghostship-agent 0.28.0 at `ea17d445` (MCP connector review). `t3_task` op `submit` now accepts the model options that `t3` op `capabilities` lists, for example `{"effort": "high"}`, plus a `runtime_mode`. It checks both against the live catalog and reports the selection it used and the thread `url`, falling back to a deep link if the link lookup fails. Capabilities lists options compactly and can be filtered by `instance_id`. Errors for invalid arguments now name the argument and the limit it broke. Filesystem denials list the allowed roots and the container paths that map into them. `browser_op` `extract` accepts a `selector` and fails when given neither `js` nor `selector`, instead of returning null. Only the `ghostship-private-integrations` MCP runtime changes behavior.

## [3.15.150] - 2026-10-20

- `ghostship-apparmor-review` can review the learning ledger by group. `--summary` lists unreviewed events grouped by their kept fields, with digits normalized and hex `comm` decoded. `--container NAME --match FIELD=GLOB` classifies every matching event in one locked write; profile and operation matches are required. The new `resolved-by-policy` classification, whose note must cite a PR, clears legitimate events a deployed policy now covers. Before this, only `expected-denial` cleared an event, so fixed events blocked enforcement forever, and reviewing 126k Plex events one ID at a time rewrote a 48 MB ledger on every call. Events now keep the AppArmor `peer`, so ptrace and signal records are distinguishable.

## [3.15.149] - 2026-10-20

- Failed services start T3 repairs. `ghostship-failure@` alerts now also go into a root-owned incident spool. The GitHub coordinator (ghostship-agent 0.28.0) turns each one into a T3 thread that diagnoses the failure on the host, fixes the cause through a PR and deploys it, and leaves `t3code` alone. A repeat failure messages the same thread, and at most 3 incident threads start per day; past that, the alert goes to a human on `operations`. Incident details never reach GitHub.
- Update notices: a nightly `nixos-upgrade` that changes the running system posts the new release to `informational`. Container auto-updates post the list of updated containers there too, and the run fails, raising an incident, when a container update fails or rolls back. The maintenance lock is now taken inside the update runner.
- Removed the Uptime Kuma HTTP monitor for the webhook receiver. Kuma can't reach the receiver's internal network, so the monitor failed every minute. The receiver's container heartbeat still covers it.
- Fixed `ghostship-desktop-bridge.timer` and `agent-desktop-mcp.timer`. Their `OnUnitActiveSec=daily` was invalid and ignored by systemd, so they now use `1d`.

## [3.15.148] - 2026-10-20

- Enable source-preserving EPUB imports through Ghostship's filesystem service: allow the existing Books library root and check Grimmory access with its configured application uid/gid. Pin the agent release with bounded EPUB inspection, collision-safe copy and the Grimmory scan/read-back workflow.
- Run the unprivileged Books EPUB converter every five minutes, with network isolation and memory/CPU limits. It retains originals and publishes validated EPUBs beside stable imported files; MCP can queue the same fixed job and inspect its report. Chaptarr's completed-download path does not implement its conversion toggle.
- The pinned MCP also discovers active T3 threads and live model/harness availability, accepts canonical thread IDs, and sends updates to existing running threads.

## [3.15.147] - 2026-10-20

- Pin ghostship-agent 0.27.2 (`de0f9588`): the GitHub coordinator routes a base-branch CI failure to the T3 thread whose merged pull request produced the failing commit (the regression issue is filed owned by that thread and the thread is messaged) instead of launching a new thread; unowned failures launch as before. Only `ghostship-github-coordinator` changes behavior.

## [3.15.146] - 2026-10-20

- `ghostship-apparmor-review` reads only AppArmor audit records (type 1400 and 1501–1507), kernel messages and journald rate-limit notices. Its daily read had covered every audit record, 1.28M lines (1.5 GB) taking 39s, past a 20s timeout. That marked every profile `audit-collection-failed` and reset each learning window daily. The read now takes about 10s, with a 120s limit, and the unit gets 15 minutes. Audit loss now matches only `audit`/`apparmor` rate-limit lines, not unrelated kernel ones such as NFS `rpc_check_timeout: N callbacks suppressed`.
- Plex profile (complain): Podman's `curl` healthcheck gets a `healthcheck` child profile with its exact libraries, resolver/TLS files and TCP. Under enforcement it would otherwise be denied, and `--health-on-failure=kill` would kill Plex. Before this, each run logged about 100 records under a null profile, about 12k an hour. The `PMS GTP` thread may `ptrace` read its own `//server` peer, to read its processes' /proc entries (no tracing).

## [3.15.145] - 2026-10-20

- Pin ghostship-agent 0.27.1 (`e0213afd`): fixes the `printing-press.sh` quoting regression from 0.27.0 that left `ghostship-inference-scheduler` crash-looping after 3.15.144.

## [3.15.144] - 2026-10-20

- Pin ghostship-agent 0.27.0 (`2b64a6d8`): skill families collapse into routers with linked guides, so 44 installed skills become 12 and the ChatGPT GhostShip Skills plugin goes from 26 skills to 5. `ghostship-skills-reconcile` installs the T3 set (pruning the retired links) and republishes the plugin. The MCP instructions now point shopping at the `shopping` skill, so the ChatGPT connector is refreshed after the switch.

## [3.15.143] - 2026-10-20

- `ghostship-cloudflare-sync` retries Cloudflare reads twice (after 5s and 20s) on HTTP 429, 5xx and network errors. A single HTTP 504 at 04:25 UTC failed the sync during the nightly `nixos-upgrade` activation, which marked the whole upgrade failed (status 4) and sent a failure notification. Writes and other client errors still fail immediately, so a write is never sent twice.

## [3.15.142] - 2026-10-20

- The host firewall accepts DNS from the internal `ghostship_github_net` (10.89.9.0/24) to its own aardvark-dns at 10.89.9.1, and nothing else. Netavark adds no DNS input rule for internal networks, so `ghostship-hooks` had no working resolver and cloudflared's second nameserver timed out on about a fifth of its queries; the flow observer recorded these as dropped. Aardvark never forwards an internal network's queries upstream, so the network still has no egress.

## [3.15.141] - 2026-10-19

- Pin ghostship-agent 0.26.0 (cba1ad46): the GitHub coordinator publishes T3 progress to `informational` (thread launched, PR opened and merged, issue closed) and base-branch regression issues to `operations` at priority 4, each once, without holding GitHub routing on an ntfy outage.

## [3.15.140] - 2026-10-19

- Notification coverage is declared once in `notify-coverage.nix`: every `ghostship-*` and `podman-*` service and a named list of other custom units report failures to `operations` through `ghostship-failure@`, which now names the unit's description, result and exit status. Previously 17 units had a failure path; the containers, brokers, bridges, network setup units and download helpers failed silently. Exemptions carry a reason, and evaluation fails when a covered unit loses its path or the module names a missing unit.
- Backup jobs post their restic summary lines silently to `informational` through the new `ghostship-success@`.
- New daily `ghostship-storage-check` alerts `operations` when the root filesystem is read-only or a Btrfs device error counter is nonzero.

## [3.15.139] - 2026-10-19

- `ghostship-synology-health` polls the Synology NAS every 10 minutes over SNMPv3 authPriv (SHA, AES) and publishes to the operations topic: system status, power and fan failures, system and disk temperature, disk status and health, degraded or crashed RAID, and `/volume*` usage at 85% and 95%. Each finding fires once, repeats daily while it persists and resolves when it clears; a failed poll raises its own alert and keeps the earlier ones active instead of resolving them. The SNMP user is the new `synology-snmp` secret unit (Bitwarden `chill-penguin/synology`); its passphrases reach net-snmp through a private `snmp.conf`, never the command line. The unit alerts through `ghostship-failure@`. Until SNMPv3 is enabled on DSM with those credentials, the poll alert fires daily.

## [3.15.138] - 2026-10-19

- Recorded the user's decision that Plex's router forward is manual, with UPnP and NAT-PMP declined. The public-service policy notes that Plex stays on manual port mapping, and that its NAT-PMP requests to the bridge gateway stay dropped. Verified: the host firewall already drops UDP 5351 from the container bridge, and SSDP does not leave the bridge.

## [3.15.137] - 2026-10-19

- Flow verdicts compare accepted connections against a new per-edge `checked` count: the connections collected while the accepted sets were loaded. Comparing against the full `connections` history left every edge recorded before 3.15.136 stuck at `partial` or `unknown`. Existing edges restart their verdict counts once; a collection missing the accepted sets does not add to `checked`.

## [3.15.136] - 2026-10-19

- The flow observer records verdicts. Accepted-connection sets at priority +20 on the inet forward/input and bridge forward hooks sit after every host filter, so each edge now carries an `accepted` count beside `connections`. `ghostship-flow-report` labels edges `accepted`, `dropped`, `partial`, or `unknown` for edges recorded before this change. Unsolicited WAN probes and blocked attempts can now be told apart from real paths when the allow graph is derived.

## [3.15.135] - 2026-10-19

- `ghostship-security-check` keeps the addresses of host SSH clients (T3, the tunnel connector) allowed for a day after they change. Logins read from the journal can predate T3's recreation, and checking them only against its new addresses produced a critical alert after each idle redeploy.

## [3.15.134] - 2026-10-19

- The GitHub coordinator joins its own `ghostship-github` group as well as the spool group, so it can read its T3 session token. Without it, issue launches retried with "t3 executable not found".

## [3.15.133] - 2026-10-19

- Keep the webhook spool and coordinator state under `/var/lib/ghostship-github`. systemd-tmpfiles refused to create root-owned directories under the `apps`-owned `/srv/apps`, so the receiver and coordinator could not start on 3.15.132.

## [3.15.132] - 2026-10-19

- Add `hooks.ghostship.io`, the webhook receiver for GitHub-driven T3 engineering and Cloudflare alerts (ghostship-agent 0.25.0, pinned at `d61a5415`):
  - Cloudflare Access bypasses exactly `POST /github` and `POST /cloudflare` (the owner 2026-10-19, recorded as `cloudflareBypassApproval`); every other path still requires Google identity. The receiver verifies GitHub's HMAC signature or the Cloudflare webhook secret itself, runs AppArmor-confined in complain mode, and shares an internal network only with cloudflared. It has no egress.
  - The registry gains `cloudflareBypassPaths`, which requires an approval and an AppArmor profile. `ghostship-cloudflare-sync` accepts a path-scoped Access app only when every domain is an approved exact path and the app's only policy is bypass-everyone.
  - The coordinator re-reads each GitHub event from GitHub and routes your issues, comments, reviews and PRs to one T3 thread per issue. It files regression issues for failing base-branch CI and publishes Cloudflare alerts to ntfy.
  - New encrypted unit `hooks` (`GITHUB_WEBHOOK_SECRET`, `CLOUDFLARE_WEBHOOK_SECRET`; copy in Bitwarden `hooks.ghostship.io`).

## [3.15.131] - 2026-10-19

- The flow collector remembers each container's addresses for a day, so connections recorded before Podman recreated a container (and gave it a new address) keep the container's name instead of `lan:<address>`. A reused address always belongs to its current owner.
- `ghostship-flow-report` accepts report options without the `report` subcommand, e.g. `ghostship-flow-report --json --since-hours 6`.

## [3.15.130] - 2026-10-19

- `ghostship-security-check` resolves the containers allowed to log in to host SSH (`host_ssh_clients`: T3 and the tunnel connector) to their current addresses on every run. Podman gave T3 new addresses when it was recreated, and the fixed list made every T3 login a critical alert. Repeated logins from one unexpected source collapse into one finding with a count.

## [3.15.129] - 2026-10-19

- Keep Podman containers confined across AppArmor reloads. Podman loads its own `containers-default-<version>` profile at runtime, and the `aa-remove-unknown` step of every NixOS AppArmor reload unloaded it, so each nightly switch left every container without its own profile unconfined. The same default rules are now declared as `ghostship-container-default` (enforce) and set as Podman's default profile, so reloads replace it instead. Container units without their own profile now also start after `apparmor.service`.
- `ghostship-security-check` compares every running container's live AppArmor label with its configured profile or the one Podman recorded, and flags containers created without a profile unless they are allowlisted privileged containers.
- Security alerts publish only through `ghostship-notify` from `config.ghostship.notify.package`; the `ghostship-alert` fallback is gone.

## [3.15.128] - 2026-10-19

- ntfy carries exactly three topics, `security`, `operations` and `informational`; `publisher` writes and `android` reads all three, and the host operations broker may publish to each.
- `ghostship-notify` replaces `ghostship-alert` as the host publisher: `--topic`, `--priority` (5 act now, 4 actionable, 3 today, 2 informational, 1 digest), `--source` and `--state` as the first two tags, optional `--dedupe` (one publish per key and state per hour, recorded only after a successful publish) and `--click`. Failed-unit notifications use it on `operations` at priority 4.

## [3.15.127] - 2026-10-19

- Add observe-only connection inventory for chill-penguin (issue #102). nftables flow sets on the inet forward/input and bridge forward hooks record each new connection's source, destination, protocol and port without returning verdicts, including attempts later dropped by the FlareSolverr egress rules. `ghostship-flow-collect` resolves addresses to container names every five minutes into a root-only edge map; `ghostship-flow-report` prints it. The map is the evidence base for the declarative allow graph.
- Add `ghostship-security-check`, run every 15 minutes:
  - Invariants alert immediately: AppArmor enabled, declared profiles loaded and attached to their containers, audit enabled with no lost events, expected firewall tables present. Also unexpected privileged containers, added capabilities, host sockets, host namespaces or undeclared containers.
  - Root SSH logins from unexpected sources and SSH failure bursts alert as one-off events.
  - Drift checks baseline first, then report new listeners, SSH key or sshd config changes, non-store unit or cron files, and new SUID/SGID files (scanned daily); `--accept` re-baselines after review.
  - Containers opening host SSH or another app's database are flagged from the flow map.
  - Alerts go to the `security` NTFY topic through `ghostship-notify` with dedupe keys and resolved notices, falling back to the existing operations alert until the NTFY topic rollout lands.

## [3.15.126] - 2026-10-19

- Start T3 Code tool maintenance within ten minutes of a new Codex, Claude, OpenCode or Grok release, using the npm registry check that drives T3's provider update notice. The existing idle and OpenCode process guards still apply.

## [3.15.125] - 2026-10-19

- Trim T3 Code's OpenCode model list: `t3code-opencode-model-catalog` rebuilds a models.dev catalog from OpenCode's cache at server start and every tool auto-update, keeping Ollama Cloud, OpenCode Go and OpenRouter models released in the last 183 days that support tool calls (OpenRouter free models only) plus the configured default and small models; other providers pass through. T3 Code's OpenCode reads it through `OPENCODE_MODELS_PATH`, because OpenCode 2 ignores provider whitelists. Today this lists 57 models instead of 446, so `orchestrator_capabilities` shrinks by about 120 KB. The free-inference pool's isolated OpenCode keeps the full catalog.
- Pin ghostship-agent f3f73aba (0.24.2): Ghostship MCP results for coding agents are bounded at 32 KB; ChatGPT keeps 96 KB.
- Stop registering direct `bladebro`/`bladebro-personal` MCP servers in every coding agent and remove the existing entries; their host-side wrapper paths never resolved inside the container, so every session failed to spawn them. Agents use Bladebro through the Ghostship browser tools; the SSH wrappers and pinned host key remain.

## [3.15.124] - 2026-10-19

- Add a Plex AppArmor profile in complain mode, separating startup utilities from the server domain and pinning executable/library paths to the inspected container.
- Include the AppArmor parser in Podman's wrapper so profile attachment works after the first AppArmor boot.
- Expose AppArmor tunables at their standard path so Podman's default profile compiles for other containers during a full system activation.
- Drain AppArmor learning events with auditd and bounded root-only log rotation, avoiding kernel printk suppression during startup bursts.
- Require declared Internet-facing apps to carry enabled AppArmor policies and recorded explicit approval for access outside Cloudflare Access. Attach profiles through Podman and fail startup when a profile is unavailable; isolate dynamic interpreters with minimal resource permissions.
- Revoke ntfy's native-auth Cloudflare Access bypass, require identity protection for explicit tunnel routes, reject unauthenticated preflight and unscoped service-token admission in both tunnel provisioners, and retain an additional ntfy AppArmor profile behind Access.
- Collect private daily audit evidence with confinement checks, an audit heartbeat, journal continuity checks, and a seven-day observation window that resets on policy/image/boot changes or telemetry gaps. Document daily review and the transition to enforcement.
## [3.15.123] - 2026-10-19

- Pin Ghostship Agent at `68d0549a` to expose NAS filesystem inspection and no-overwrite moves.
- Limit the broker to Downloads, TV and Movies on the NFS-mounted NAS; derive Sonarr, Radarr and Plex access-check identities from their container users.

## [3.15.122] - 2026-10-18

- Pin GhostShip Agent main at `81fb9234` (free inference 0.24.0, PR #28, and 0.24.1, PR #29: OpenRouter pin drift pause, probes prefer strict routes).
  - Gate request rewriting fixes Upstage and Cloudflare.
  - New free providers: Upstage, Inception, Poolside, OVH, plus Mistral on its Free plan. OrcaRouter is enabled.
  - Routing ignores where a model was developed and fails closed on unknown aggregator hosting. OpenRouter gets a hosting allowlist pin.
  - A new `light` workload admits weaker models.
- Pool accounts:
  - Add Upstage, Inception, Poolside, OVH (anonymous) and Z.ai; enable OrcaRouter; open Mistral to all workloads.
  - Billing attestations for Upstage, Mistral and Inception.
  - `china_hosting_workloads: ["research"]` on the aggregator and research accounts (the owner 2026-10-18: free research may include China providers; Singapore is fine).
- Project Z.ai's key (`ZHIPU_API_KEY`) from a new encrypted provider unit.

## [3.15.121] - 2026-10-18

- Free inference pool reads its credentials from a copy in the T3 container's tmpfs `/run` (`GHOSTSHIP_FREE_INFERENCE_PROJECTION`), refreshed by the bridge prepare step and a path unit whenever `/run/ghostship-secrets/t3code.env` changes. The container's single-file bind mount keeps the old inode after the projector's rename, so new provider keys stayed invisible without a T3 restart.

## [3.15.120] - 2026-10-18

- Pin Ghostship Agent main at `e714db00` to activate the lean engineering workflow, writing standard, manual pattern review and repository cleanup skills, with verified behavioral evaluation fixtures.

## [3.15.119] - 2026-10-18

- Pin GhostShip Agent main at `5c176689` (free inference pool as the first-class worker framework, PR #26): registry as data with live probes, bounded OpenCode agent jobs (request budgets, allowlisted fetch, confined sandbox), adaptive concurrency and client shares, admission benches, no China-hosted routes by default.
- Project the free-provider keys Kilo, Requesty, OrcaRouter, Inception, Mistral, Upstage and Poolside into `t3code.env` from new encrypted provider units.
- Pool: 8 workers (goship-research 0.7 / default 0.3), scheduled probes and admissions; un-suspend NVIDIA (research allowed) and Cloudflare Workers AI; Vercel free-only without `beam-free`; enable keyed Kilo and Requesty, and Mistral for evaluation.

## [3.15.118] - 2026-10-18

- Start the free inference bridge only after the T3 container's `t3code-container-setup` finishes: its boot-time `chown -R t3code:t3code ~/.local` reset the bridge socket and token to group `t3code` after the bridge set group 62020, so every MCP `inference_*` call returned "unavailable" after the 2026-10-17 container replacement.

## [3.15.117] - 2026-10-17

- Preserve existing research launchers on OpenCode 2 and provide an OpenCode-only activation command without restarting T3.
- Stage OpenCode 2 from its separate stable package in verified immutable releases, preserving the old executable on failure and requiring an explicit first database migration.
- Never trust the stale V1 database once T3 has migrated to V2; missing databases also block host deployment. V2 activity uses the `v2-sqlite` probe from 3.15.114.
- Add disposable-container release and database-migration smoke checks and a maintenance-only safety guard that preserves the active runtime.
- Stop projecting `OPENCODE_API_KEY`: OpenCode retired API keys, and the expired key shadowed OAuth logins and made Zen reject even free models.

## [3.15.116] - 2026-10-17

- Pin GhostShip Agent `main` at 0.22.1 (free inference pool and relay health
  merged; content identical to the previously deployed branch pin).

## [3.15.115] - 2026-10-17

- Fully retire CloakBrowser: quarantine `/srv/apps/cloakbrowser` profiles and
  extensions into `/srv/retired-apps` and remove the runtime masks that
  outlived its units.

## [3.15.114] - 2026-10-17

- Clear runtime drop-ins and shadowed runtime unit links of declared units on
  every full switch; a leftover targeted-activation drop-in kept rendering the
  ChatGPT relay with a removed MCP runtime path. Runtime masks stay.
- Detect T3 Code 2 activity from `statev2.sqlite` in the idle-deploy probe
  (open runs, subagents and launches, recent user messages and turn items), so
  queued T3 updates no longer need a disabling override or session guard.
- Pin GhostShip Agent 0.22.1: a crash-looping relay now marks the MCP
  container unhealthy and `integration_status` reports the relay state.

## [3.15.113] - 2026-10-16

- Keep scheduled T3 source sync on the host-projected managed installer so an
  older running image cannot reinstall an obsolete CLI or shared instructions.
- Share the existing guarded repository sync between future images and the
  session-safe service override; retain timer behavior and provider settings.

## [3.15.112] - 2026-10-16

- Allow selected private-file inference reviews in the approved Ghostship
  checkout and derive broker repository roots from the shared pool policy.
- Retain the public fixture and its repository-specific trusted test command.
- Keep Cohere request ceilings unchanged while allowing a documented internal
  500k-token daily ceiling and bounded 4096-token review output.
- Refresh the pinned managed CLI during inference activation while preserving
  provider configuration and global Git settings.

## [3.15.111] - 2026-10-16

- Pin the inference MCP response contract fix so live status, cancellation, and
  paged result responses reach clients after the durable broker operation.

## [3.15.110] - 2026-10-16

- Pin Ghostship Agent 0.22.0 and run separate supervised inference broker and
  scheduler processes in T3, with a dedicated encrypted token and a local Unix
  socket for the MCP.
- Persist the worker pool's provider policy and public synthetic fixture
  separately from the main OpenCode configuration.

## [3.15.109] - 2026-10-16

- Add encrypted inference provider bundles for Groq, Google AI Studio, NVIDIA,
  Hugging Face, Vercel AI Gateway, Cloudflare Workers AI, and Cohere, projecting
  their credentials into the T3 Code runtime environment.
- Keep the dedicated Workers AI token and account separate from Cloudflare's
  management credential bundle.

## [3.15.108] - 2026-10-16

- Pin GhostShip Agent 0.21.0: retailer skills and generic browser shopping, with Costco local warehouse inventory retained through the generic service executor.
- Retire the unused shopping overlay argument and preserve the active T3 session during activation.

## [3.15.107] - 2026-10-13

- Pin GhostShip Agent 0.20.1 for bounded shopping output, literal model matching, selected spool/variant evidence, Best Buy destination verification and read-only quantity promotion quotes.
- Preserve the active T3 session while activating the updated shopping runtime.

## [3.15.106] - 2026-10-13

- Pin GhostShip Agent 0.20.0 for exact-ASIN verification, bounded deep search, sampled price history, silent baselines and retailer cart contracts with explicit coverage gaps.
- Preserve active T3 sessions while activating the updated GhostShip runtime.

## [3.15.105] - 2026-10-13

- Keep T3 temporary checkouts on disk instead of Podman's systemd tmpfs, with a writable sticky directory and evaluated mount regression checks.
- Raise the shared memory reclaim threshold to 36 GiB, retaining the 40 GiB hard ceiling, to recover the existing RAM-backed temporary workload without restarting active sessions.

## [3.15.104] - 2026-10-13

- Contain combined T3 tool memory when anonymous allocations cause cgroup reclaim stalls, even when each tool is below 12 GiB. Protect the native T3 server behind its Node launcher and timestamp containment actions.
- Never restart T3 for memory pressure, including pressure-induced web timeouts. Memory measurements veto web recovery immediately, reset its failure streak, and are rechecked before recovery.
- Protect T3's launcher and native server from kernel OOM selection, keep tools eligible, and increase the shared reclaim/hard limits to 32/40 GiB on Chill Penguin's 64 GiB host.

## [3.15.103] - 2026-10-13

- Pin ghostship-agent 0.19.0: browser window leases lapse after 10 idle minutes and 2 hours in total, close when a coding-agent session ends, hold at most 6 tabs, sweep the popups their pages opened, and publish their expiry in the window's home tab.
- Agent Desktop: Chrome starts with no window (`--no-startup-window`), and the
  idle watcher runs `chrome-lease-reaper`, which closes windows whose
  `about:blank#ghostship-window-<token>.<expires>` lease expired more than
  `CHROME_LEASE_SLACK_SECONDS` (120) ago, with their popups.

## [3.15.102] - 2026-10-13

- Pin ghostship-agent 0.18.2: Wyze weigh-ins from the Wyze API (every weigh-in, true time zones, kg).
- New agenix unit `wyze` (`EMAIL`, `PASSWORD`, `KEY_ID`, `API_KEY`) projected to the MCP container as the `wyze` service credential.

## [3.15.101] - 2026-10-12

- Pin ghostship-agent 0.18.1: `health` op `types` and `query` over every Health Connect type, Ultrahuman lab biomarkers, full sleep and metrics, Wyze weigh-ins, and health documents with their text (OCR for scans).
- The MCP container reads health documents only from the owner's "the owner" and "HealthConnect" Drive folders (`GHOSTSHIP_HEALTH_DOCUMENT_FOLDERS`).

## [3.15.100] - 2026-10-12

- Pin ghostship-agent 0.16.3 (AlohaQ skill removed).

## [3.15.99] - 2026-10-12

- Pin ghostship-agent 0.16.2: the ChatGPT skills plugin carries all 26 ChatGPT-capable skills.

## [3.15.98] - 2026-10-12

- Pin ghostship-agent 0.16.1 (cover display guidance).

## [3.15.97] - 2026-10-12

- Pin ghostship-agent 0.16.0: the listed tool surface is compressed to about 27 KB.

## [3.15.96] - 2026-10-12

- Pin ghostship-agent 0.15.1 (facade op descriptions).

## [3.15.95] - 2026-10-12

- Pin ghostship-agent 0.15.0:
  - results are trimmed and paginated instead of dropped;
  - services take sort/limit;
  - media records carry public cover URLs;
  - ChatGPT output alignment.

## [3.15.94] - 2026-10-12

- Pin ghostship-agent 0.14.1: `health` op `sources` passes the result contract.

## [3.15.93] - 2026-10-12

- Pin ghostship-agent 0.14.0 (`main` 25cab8c6): the `health` tool (Health Connect export, Ultrahuman, Wyze scale history) and the Ultrahuman and Wyze services.
- New agenix unit `ultrahuman` (`API_TOKEN`) projected to the MCP container as the `ultrahuman` service credential.

## [3.15.92] - 2026-10-12

- Pin ghostship-agent `main` acf76bd8. The unified platform line, with every release through 0.13.1, is merged into `main`.

## [3.15.91] - 2026-10-12

- Pin ghostship-agent 0.13.1:
  - pages settle adaptively after navigation;
  - the desktop lock is held only across a batch's native-input steps.

## [3.15.90] - 2026-10-12

- Pin ghostship-agent 0.13.0:
  - the MCP server lists 15 op-dispatch tools instead of 40;
  - the ChatGPT skills bundle adds `ghostship-services` and `ghostship-browser`.

## [3.15.89] - 2026-10-12

- Pin ghostship-agent 0.12.0, which adds read and write support for every service.
- The host operations broker allowlists the config files of Homepage, Muximux, Plex Auto Languages and Recyclarr for read and replace.
- Restic restores go to `/var/lib/ghostship-backup/restore`.

## [3.15.88] - 2026-10-12

- Pin ghostship-agent 0.11.0 (regenerated service clients, confirm gates, chill-penguin host service, ntfy message polling). The host operations broker reports disk usage for `/`, `/srv`, `/nix` and the NAS share.

## [3.15.87] - 2026-10-12

- Make the rendered Seerr executor credential group-readable (0440) so the MCP container can read it.

## [3.15.86] - 2026-10-12

- Pin ghostship-agent 0.10.0 (every service executable through `services_*`).
- Add `ghostship-hostops-broker`: the agent's allowlisted host operations broker, run as root and reachable only by the MCP container user over `/run/ghostship-hostops/ops.sock`, which is mounted read-only into the container. It drives:
  - container status, logs and restart for every OCI container, except restarting `t3code` and the MCP container;
  - MariaDB reads;
  - restic status, snapshots and runs;
  - Recyclarr sync;
  - Uptime Kuma;
  - read-only Cloudflare;
  - ntfy publishing.

  Restic, Cloudflare management, Kuma and ntfy credentials stay on the host.
- Project Gluetun and Tdarr executor credentials (Tdarr: base URL only). Render Seerr's self-generated API key from its settings into its projection.

## [3.15.85] - 2026-10-12

- Pin ghostship-agent 0.9.1 (Plex, Tautulli and Grimmory service backends) and
  project their executor credentials into the private integrations container:
  the Plex token as `PLEX_USER_TOKEN`, the Tautulli API key, and the Grimmory
  application login (not its database credentials), each with the internal
  base URL.

## [3.15.84] - 2026-10-11

- Pin ghostship-agent 0.9.0 (generic service executor, explicit browser
  leases, bounded-wait jobs, skills distribution) and enable
  `skillsReconcile` on chill-penguin.

## [3.15.83] - 2026-10-11

- Project least-privilege credentials for the ghostship-agent generic service
  executor into the private integrations container (read-only at
  `/run/ghostship-secrets/<service>.env`): Sonarr, Radarr, Prowlarr, Bazarr,
  Chaptarr, pyLoad and RomM secrets plus internal base URLs for those and
  qBittorrent, NZBGet and ntfy. Projections now accept non-secret literal
  fields and unquoted (`raw`) output.
- Add `ghostship.privateIntegrations.skillsReconcile.enable` (off): a
  post-deploy oneshot that packages, publishes and verifies the ChatGPT
  skills plugin once the MCP container is healthy.

## [3.15.82] - 2026-10-11

- Raise the private integrations container memory limit from 1 GiB to 4 GiB.

## [3.15.81] - 2026-10-11

- Stop idle deploys from interrupting T3 Code work: the activity probe now treats
  unsettled Claude background tasks and any thread activity in the last 10
  minutes as active, and the deployer never restarts a unit that is mid-start.

## [3.15.80] - 2026-10-11

- Pin ghostship-agent 0.8.27 (AliExpress checkout quotes, Best Buy filament weights).

## [3.15.79] - 2026-10-11

- Pin ghostship-agent 0.8.26 (named tabs, category routing, AliExpress shipping minimums).

## [3.15.78] - 2026-10-11

- Raise the private integrations container to 512 pids and 1 GiB: parallel
  agent windows drive up to 8 Bladebro workers per identity, and the old
  64-pid cap failed worker starts with EAGAIN.
- Pin ghostship-agent 0.8.25 (one window per agent, per-retailer tabs).

## [3.15.77] - 2026-10-11

- Start Agent Desktop Chrome on demand: the agent and personal s6 services no
  longer start at boot; `chrome-ensure <identity>` starts one and waits for
  DevTools, and `svc-agent-desktop-chrome-idle` stops an identity after 10
  minutes on plain `about:blank` only. The `abc` group controls both services
  through `s6-svperms`, so crash restart stays and an idle stop stays down.
- Keep background and occluded Chrome tabs rendering and running timers.
- Accept bursts of concurrent Agent Desktop SSH handshakes (`MaxStartups
  200:30:400`), since parallel agents issue many short browser-control commands.

## [3.15.76] - 2026-10-11

- Tag and build the Agent Desktop image from its own content-addressed
  `containers/agent-desktop` context, so unrelated nixos-config commits no
  longer change `podman-agent-desktop.service` or restart the desktop.

## [3.15.75] - 2026-10-10

- Pin ghostship-agent 0.8.24: the Ghostship MCP adds the read-only `orca_profiles`
  tool for Orca Cloud profiles on the Assistant identity.

## [3.15.74] - 2026-10-10

- Prepare offline Boomer security fixes: run setup and controller state as kiosk,
  confine privileged LED writes, protect Bluetooth logs/locks, and bound event work.
- Copy homebrew assets without following symlinks, keep Wi-Fi passwords off argv,
  replace unsafe secret fallbacks, and bound performance-log classification.
- Repair PICO-8 aliases, retired Tools links, console TUI output, controller policy
  metadata, and exact Star mapping tests; retain owner-accepted emulation risks.

## [3.15.73] - 2026-10-10

- Remove the active private relay identifier from public integration documentation.

## [3.15.72] - 2026-10-10

- Read existing Kuma notification types from their serialized configuration,
  preserving the notification ID while updating the ntfy URL and credential.

## [3.15.71] - 2026-10-10

- Replace Homepage's host Podman socket with a restricted read-only Unix
  broker; deny container inspection, logs, archives, execution, and control.
- Restrict FlareSolverr to public-site egress while retaining internal API
  access and Podman DNS. Cover both bridge peers and routed traffic.
- Require protected approval for private-source CI and migrate RomM's existing
  root accounts to an encrypted password, including authenticated backups.
- Remove host-root file mutations from desktop MCP provisioning,
  qBittorrent configuration, and Tdarr node configuration. Keep
  auto-resume state outside the container's writable tree.
- Harden XML parsing, require critical secrets before config writes, accept
  interspersed config CLI options, and protect NZBGet/Docker Hub credentials.
- Keep VPN credentials out of curl arguments, preserve fallback ordering,
  reconcile existing ntfy alerts, refresh T3 bridge tokens, and keep GC from
  starting a stopped T3 container. Hold the upgrade maintenance lock throughout
  the build and switch.
- Scope iframe-audit Access headers to trusted HTTPS origins and recheck each
  redirect; remove inline-token deployment guidance. Prune OpenCode events
  under SQLite's write lock without replacing live clients' database inode.
- Preserve independent ACP request IDs and handle missing retailer page titles
  and command failures. Preserve dynamic RomM WebSocket paths and queries.
  Add hourly recovery after RomM exhausts its bounded restart window.
  Record retained trust choices and defer emulation work.

## 3.15.70

- Integrate shared MCP/browser/GUI activation with main’s T3 activity-probe and retention fixes, preserving active-session restart protections.

## 3.15.69

- Pin the desktop locking correction: outer MCP batches and nested workers acquire both profile locks in the same order.

## 3.15.68

- Pin the retired-browser platform and managed Bladebro/GUI wrappers to the shared MCP source and package.
- Normalize Pelorus control responses so successful backend input returns a valid REST result; preserve errors and reject unknown responses.

## 3.15.67

- Retire CloakBrowser completely: remove its service, extension timer, dashboard route, installers, and T3 environment/wiring. Cleanup removes retired execution artifacts and images while preserving saved profile data.

## 3.15.66

- Install coding-agent commands from the same pinned Ghostship package as the shared MCP. Boot and periodic source sync no longer rebuild an older main checkout over the tested connector.

## 3.15.65

- Pin Ghostship MCP 0.8.20: verified checkbox activation and worker transport recovery. Live ChatGPT tool validation remains skipped as requested.

## 3.15.64

- Clear only Chrome tab/session restoration files before managed launch so an unclean exit also starts fresh. Preserve cookies, credentials, history, and site storage.

## 3.15.63

- Start Agent Desktop Chrome with a fresh tab after relaunch while preserving profiles and sign-ins. Disable background mode, Memory Saver discarding, and background tab freezing for predictable browser workers.

## 3.15.62

- Pin Ghostship MCP 0.8.19: bounded worker RPC framing, guarded SSH startup, and private loopback OAuth callbacks. ChatGPT authentication remains deferred.
- Set the Agent Desktop task bound to 4,096 under its existing 16 GiB memory bound after parallel browser workloads reached the default 2,048-task limit. Apply the task bound without restarting T3 or the desktop container.

## 3.15.61

- Pin Ghostship MCP 0.8.17: resilient coding connections without tool replay, exact owned-tab lifecycle, and collector context support. ChatGPT authentication remains deferred.

## 3.15.60

- Pin Ghostship MCP 0.8.15: native-input workflow transactions, Drive row selection, and observed item identity/fee evidence. ChatGPT authentication remains deferred.

## 3.15.59

- Pin MCP 0.8.14 accessible role actions and foreground native-input isolation; DOM reads remain parallel. Full retailer/Google/consumer acceptance remains pending.

## 3.15.58

- Pin MCP 0.8.13 Target native title/identity extraction and unknown variant price ranges. Full retailer/Google/consumer acceptance remains pending.

## 3.15.57

- Pin MCP 0.8.12 fresh offer evidence, bounded parallel verification and compact job history. Full retailer/Google/consumer acceptance remains pending.

## 3.15.56

- Pin MCP 0.8.11 typed retailer failure outcomes with conservative interrupted-mutation uncertainty and no replay. Retailer and cached client acceptance remain incomplete.

## 3.15.55

- Pin MCP 0.8.10 fresh-price/condition/eligibility evidence and concurrent job-store initialization fixes. Full retailer and cached client acceptance remain pending.

## 3.15.54

- Pin MCP 0.8.9 product matching, rejecting conflicting selected variants and incomplete verified identity evidence before ranking offers. Full retailer and client acceptance remain pending.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.15.53] - 2026-10-09

- Pin shared MCP 0.8.8 with durable tab/job ownership across PID namespaces,
  interrupted-write reconciliation without replay and explicit diagnostic limits.
- Restore the previous session when managed desktop Chrome restarts. Renderer
  hang root cause and unattended recovery remain pending acceptance.

## [3.15.52] - 2026-10-09

- Pin shared MCP 0.8.7: coding agents and the OpenAI relay use one persistent
  canonical backend with independent sessions and reusable identity-bound workers.
  Connector refresh and broader shopping acceptance remain pending.

## [3.15.51] - 2026-10-09

- Pin shared MCP 0.8.6 with Standard search budgets, canonical product matching,
  destination/offer safeguards and bounded per-worker diagnostics. Retailer
  workflow and price benchmark acceptance remains pending.

## [3.15.50] - 2026-10-09

- Align the shared MCP and coding-agent package at 0.8.5, including the
  verified installed eBay client module path. MCP schemas remain unchanged.

## [3.15.49] - 2026-10-09

- Pin shared MCP 0.8.4: browser-only eBay active/sold/completed evidence,
  explicit sign-in outcomes and retired legacy/API clients. Unknown mandatory
  fees require checkout evidence; listing location no longer implies zero fees.

## [3.15.48] - 2026-10-09

- Update the shared Ghostship MCP to 0.8.3: exact-tab ownership checks,
  interrupted-worker cleanup, independent primary/detail pages, concurrent
  registry reconciliation and accurate mutation idempotence annotations.
  Worker fixtures passed 100 rounds at 1/2/4/8 workers in both identities.

## [3.15.47] - 2026-10-09

- Pin the shared Ghostship MCP to the tested 0.8.2 catalog and browser runtime.
  Coding agents and the private ChatGPT relay use the same server. Integration
  diagnostics expose the pinned source revision, image tag, catalog hash, and
  backend connectivity for deployment and connector discovery checks.

## [3.15.48] - 2026-10-10

- **Fix the T3 Code retention OpenCode prune**: the retention wrapper ran
  `packages/t3code/retention.py` as a lone store file, so its
  `load_opencode_prune()` sibling lookup resolved to
  `/nix/store/opencode-db-prune.py` and failed on every run. OpenCode's
  unbounded event log was never rebuilt, which is why `opencode.db` reached
  10 GiB. Bundle both modules in one store directory so the sibling import
  works, and assert the bundled invocation in `tests/test_t3code_retention.py`.

## [3.15.47] - 2026-10-10

- **Stop mid-turn T3 Code restarts**: the shared activity probe that gates
  tool maintenance, memory recovery, and host deployments only counted a turn
  as running while its `completed_at` was null. T3 Code stamps `completed_at`
  on a running turn when a mid-turn checkpoint diff completes, so a long Codex
  or Claude turn stopped counting as active once its pending request and user
  message windows lapsed. The server monitor then restarted
  `t3code-server.service` for sustained memory pressure and interrupted the
  work that was still running (observed on 2026-10-10 at 06:28 and 08:20 UTC).
  The probe now also treats a provider session that is starting or running as
  active work, the same authoritative signal T3 Code uses to keep a turn
  unsettled. Regression tests cover a checkpointed running turn and sessions
  without a turn row.
- **Keep the retention timer alive across store GC**: `t3code-retention` was
  missing from the container image contents, so the daily isolated-store GC
  deleted its binary and the enabled `t3code-retention.timer` failed to exec
  with no log line. OpenCode's unbounded event log then grew to 10 GiB
  (`event` table alone 8.5 GiB), server traces exceeded the retained count, and
  the container previously hit ENOSPC on 2026-09-30, breaking tool updates and
  agent installs. Add the retention package to the seeded and rooted image
  contents, and assert in `checks.nix` that `podman-t3code` seeds it.

## [3.15.46] - 2026-10-09

- **Garbage-collect the T3 Code container's isolated Nix store**: the container
  keeps its own persistent store at `/srv/apps/t3code/nix-root/nix`. Every image
  deployment `nix copy`s a fresh closure into it and agent sessions build into
  it, but nothing ever collected it, so dead paths accumulated without bound.
  A daily `t3code-nix-store-gc` timer now runs `nix store gc` inside the running
  container under the shared maintenance lock. GC removes only paths unreachable
  from GC roots, so live profiles, active sessions, and in-flight builds are
  preserved, and it never restarts the container. It skips when the container is
  not running.

## [3.15.45] - 2026-10-08

- Validate the Bladebro driver across Home Depot, Lowe's, Amazon, Walmart
  and Target: all five load with distinct products and prices and no
  challenge markers.
- Record the concurrency results (three parallel agents with separate tabs,
  independent Agent/Personal profiles, client kills leaving Chrome and tabs
  intact, authentication surviving a Chrome restart).
- Document the driver policy (Bladebro default, Playwright optional, Pelorus
  for native and CDP-incompatible sites) and the upgrade/rollback runbook
  for the pinned Chrome and Bladebro versions.

## [3.15.44] - 2026-10-08

- Add the CDP detection test tooling (dependency-free client, local detector
  page, variant matrix, retailer journey runner) and document the isolation
  result: `Runtime.enable` is the only operation deviceandbrowserinfo's
  detector observes, while attachment, Page/Network/DOM/Accessibility/Input
  and one-shot evaluation stay clean.
- Validate Home Depot end to end with Bladebro real-lane attach and the raw
  minimal CDP client; Playwright and Runtime-enabling clients remain blocked.
- Evaluate the Chrome extension transport: branded Chrome 155 ignores
  `--load-extension`, so non-CDP alternatives need enterprise policy or
  native desktop control.
- Harden the CDP regression runner to fail on missing results, zero page
  samples, Chrome startup failures and unsuccessful commands, and load the
  desktop session environment so timers or `podman exec` can run the tools.
- Strengthen the retailer runner: live product links only, distinct product
  counts, page-completeness markers, explicit 403/challenge detection, and
  a reload step; the no-CDP control stays screenshot-only.

## [3.15.43] - 2026-10-08

- Restore PulseAudio and add Noto Color Emoji so the desktop browser exposes
  real audio devices and emoji fonts instead of container-only stubs.
- Ship the CloakBrowser detection/fingerprint bookmark set as managed Chrome
  bookmarks on both profiles.
- Record that Akamai/PerimeterX detect active CDP clients: Home Depot works
  without CDP (manual Selkies or Pelorus input) and returns 403 to
  Bladebro/Playwright sessions.

## [3.15.42] - 2026-10-08

- Run Google Chrome as a native Wayland client so Selkies touch gestures
  and Pelorus scroll injection reach the browser; XWayland Chrome ignored
  compositor wheel events, which broke touch scrolling and manual scroll.

## [3.15.41] - 2026-10-08

- Replace Camoufox in the agent desktop with Google Chrome stable, pinned by
  version and SHA-256, as the default LXQt/XDG browser; retire the Camoufox
  runtime, browser cache and Playwright WebSocket forwarding.
- Run persistent Agent and Personal Chrome instances under independent s6
  services with fixed loopback DevTools ports and profile directories that
  preserve authentication across restarts and image updates.
- Integrate Bladebro, pinned by version and SHA-256, in real-browser attach
  mode and provision its MCP servers automatically for t3code over SSH with a
  pinned desktop host key.
- Keep the browser environment coherent for mainstream sites: match the
  container timezone to the egress location, pass through `/dev/dri` so
  Chrome reports the real GPU instead of disabled WebGL, and re-enable
  Chrome's sandbox. Lowe's search and product pages now load with
  structured extraction.
- Launch Chrome with a deliberately minimal command line (custom profile,
  loopback DevTools port, first-run/crash UX suppression, locale and window
  size only) and add `ghostship-chrome-instance` for on-demand instances.
- Keep Pelorus native GUI control and the authenticated desktop proxy with a
  reduced Pelorus-only surface.

## [3.15.40] - 2026-10-08

- Add the Ghostship agent desktop: a persistent LXQt + labwc Selkies
  workstation on `chill-penguin` built from the LinuxServer `ubuntu-lxqt`
  image with pinned Camoufox/Playwright, Pelorus AT-SPI desktop control, key
  based SSH and supervised browser owners.
- Expose a token authenticated automation proxy on a private
  `agent_desktop_net` shared with t3code, and route `desktop.ghostship.io`
  through the existing Cloudflare tunnel and Access policy.
- Document the endpoints, profiles, GUI automation, updates and recovery in
  `docs/agent-desktop.md`.

## [3.15.39] - 2026-10-06

- Provide `git` to the `ghostship-config-tests` derivation; the t3code retention
  test invokes `git worktree` and failed in the sandbox without it.

## [3.15.38] - 2026-10-06

- Build the private MCP sidecar from the extracted `ghostship-tools` platform
  (`ghostship-private-tools`) instead of `ghostship-agent`.
- Update the CI private-source importer to recognize the renamed input and
  preserve its `dir = "ghostship-tools"` subdirectory.

## [3.15.37] - 2026-10-05

- Add a daily `t3code-retention` service that rotates oversized operational logs,
  prunes OpenCode's unbounded SQLite event log, archives settled threads after
  7 days, deletes threads idle for 180 days through the orchestration API, and
  removes archive-only worktrees under `~/.t3/worktrees` when no active thread
  still shares the path.
- Point the OpenCode launcher at a home-backed `TMPDIR` and clear the
  `NO_COLOR`/`FORCE_COLOR` conflict that polluted every OpenCode stderr line.

## [3.15.36] - 2026-10-03

- Pin the verified merged Ghostship Agent revision for private Keep and Amazon deployment.
- Record native host verification and next-boot generation 238 while preserving the active T3 session.

## [3.15.35] - 2026-10-03

- Deploy Keep create/update with separate titles, checkbox row patches, labels, image attachments and label/tag searches; preserve the active T3 session.

## [3.15.34] - 2026-10-03

- Deploy the Amazon multiword-query schema fix for the connected ChatGPT host.

## [3.15.33] - 2026-10-03

- Refresh pinned integration sources after reconciling current shopping and host changes.

## [3.15.32] - 2026-10-03

- Fix Keep session recovery by preserving Google session authentication timestamps;
  verify all eight personal Keep tools and four Amazon reads against the live host.

## [3.15.31] - 2026-10-03

- Pin the Keep navigation fix and its required public browser-client identifier;
  include the registered Assistant ChatGPT metadata workflow, delete-to-trash
  support and private cached authentication. CloakBrowser is used for auth only.

## [3.15.30] - 2026-10-03

- Route Keep accounts to Assistant/Default profiles and execute operations
  directly, retaining revision checks and durable interruption recovery.

## [3.15.29] - 2026-10-03

- Authenticate CI public host-key metadata requests with the scoped Actions token
  to avoid shared-runner anonymous API limits; record live relay evidence.

## [3.15.28] - 2026-10-03

- Pin the private integration image's shell dependency required by real Podman
  health probes, after verifying authenticated OpenAI tunnel polling.

## [3.15.27] - 2026-10-03

- Provision the encrypted Ghostship relay bundle for the owner-created tunnel,
  retaining disabled personal Keep access pending independent review.

## [3.15.26] - 2026-10-03

- Consolidate private Keep and Amazon into one Ghostship connection, official
  relay and scoped credential bundle, retaining separate service authorization.

## [3.15.25] - 2026-10-03

- Package private Ghostship Keep and Amazon MCP profiles in one immutable ARM64
  OCI image, with separate scoped official OpenAI relays and a host-only Keep
  approval broker. Personal activation remains disabled and relay provisioning
  remains owner-controlled; no inbound MCP port or T3 Code restart is required.

- **Fix pyLoad iframe blacking out on Queue or Packages**: pyLoad renders its
  Queue, Packages, Files, Logs, and Settings links plus theme assets as
  root-absolute paths (`href="/queue"`, `href="/web/..."`). Inside Muximux's
  `/pyload/` same-origin proxy those references escaped the prefix and landed on
  Muximux's own `404` page, which is the black screen users saw after clicking
  through the embedded UI. Rework the `/pyload/` and `/web/` nginx locations to
  rewrite root-absolute `href`/`url()` references back under `/pyload/`, so
  in-iframe navigation stays inside pyLoad.

## [3.15.24] - 2026-10-01

- **Restore Antigravity session startup**: T3 0.0.44 resolves `node` from
  `PATH` and refuses a runtime whose resolved path or inode matches
  `process.execPath`. The `t3-runtime-preload.cjs` shim overrode
  `process.execPath` with the pinned Node, so T3 mistook the container's Node
  for its own executable and failed every Antigravity session with
  `NodeRuntimeUnavailableError` ("Antigravity sign-in requires Node.js"). Drop
  the obsolete override; the packaged T3 now finds Node on `PATH` directly.

## [3.15.23] - 2026-10-01

- **Keep the Tdarr encoder from stalling behind policy refusals**: Tdarr stops
  handing out work once `stagedFileLimit` items sit in the review queue, and a
  full queue silently idles every worker. Every deterministic policy refusal
  (unknown original language, above 1080p, HDR, interlaced, missing audio
  language tags, commentary tracks, no original audio, foreign titles without
  English subtitles) now ends at a local `plexSkip` node that leaves the file
  untouched and records the item as done. The old flow parked those files at
  `Require Review`, which is what wedged the encoder twice. `plexSkip`
  deliberately does not use `removeFromTdarr`: deleting the record while the
  file stays on disk makes the next scan re-queue it forever.
- **Detect a full staging queue**: a 15-minute `tdarr-staged-guard` timer fails
  loudly when staging reaches 90% of its limit and reports the review count, so
  a future queue buildup is visible instead of silently idling transcodes.

## [3.15.22] - 2026-10-01

- Move RomM and Grimmory into the Muximux dropdown, add an optional Muximux
  `label` so the Homepage tile renders icon-only, and set that label empty.

## [3.15.21] - 2026-09-30

- Reclaim Btrfs metadata on a schedule and bound the churn that exhausts it.
  Add a weekly metadata balance, a weekly unused image prune, a one GiB
  journald cap, and a bounded systemd-boot entry count so the root filesystem
  can no longer fill its metadata and latch read-only while `df` shows space.

## [3.15.20] - 2026-09-30

- Project the OpenCode Go `GO_API_KEY` into the T3 Code container as
  `OPENCODE_API_KEY` so OpenCode can use the `opencode-go` provider.

## [3.15.19] - 2026-09-27

- Remove the orphaned OpenChamber and Synara HTTP monitors for retired apps.

## [3.15.18] - 2026-09-27

- Remove the unused NZBGet Gluetun namespace proxy, prune its Homepage card,
  and remove the orphaned ChatGPT card after its container retirement.
- Provision Uptime Kuma push monitors for every declared container and report
  missing, stopped, or unhealthy containers from the host timer.
- Enforce Kuma's disabled-login setting through its settings API, leaving
  Cloudflare Access as the public authentication layer.

## [3.15.17] - 2026-09-27

- Ensure Homepage's house icon widget is added when the existing widgets file
  has no logo entry, and add the XPlus4 shortcut to Muximux.

## [3.15.16] - 2026-09-27

- Allow Uptime Kuma to render inside the protected Muximux dashboard and remove
  the non-UI FlareSolverr shortcut.
- Add Homepage status entries for every container, enforce complete registry
  coverage, and show Homepage's house mark without the title text.

## Unreleased

## [3.15.15] - 2026-09-27

- **Route foreign titles without English subtitles to review**: Detect missing
  English subtitles in the source before changing streams or starting an
  encode, avoiding predictable post-encode validation failures.

## [3.15.14] - 2026-09-27

- **CloakBrowser fonts and quiet permissions**: Mount a persistent directory for
  licensed Windows fonts and refresh Fontconfig before launch; browser profile
  defaults now suppress permission prompts and crash restore bubbles.

## [3.15.13] - 2026-09-27

- **Automatic chill-penguin upgrades**: Enable nightly `system.autoUpgrade` on
  `chill-penguin` with `--impure` so Asahi firmware stays enabled, fetch the
  public repository over HTTPS, catch up missed runs after boot, wait for a
  running backup, and alert on failure.
- **Keep active T3 Code sessions running**: The server monitor no longer
  force-restarts active work for memory pressure or a missing provider; only a
  stopped server or an unresponsive web UI can interrupt active turns.
- **Resume interrupted T3 Code deploys**: Stamp containers with their deployment
  ID and record an already-running image as applied instead of restarting it
  again. Share the tool-maintenance lock with the host deployer through the home
  bind mount and hold it across the container restart. A host switch no longer
  restarts an in-flight deploy.
- **Skip needless T3 Code restarts**: Ghostship tool package changes no longer
  queue a server restart.
- **Bounded recovery from a broken T3 Code image**: Adopt a running new image
  only once healthy, wait out its start period, retry an unhealthy one at most
  three idle-gated times, alert on each failed start, then stop until a new
  image arrives.
- **Sync shared source checkouts**: Fast-forward `/workspace/ghostship-agent`
  and `/workspace/nixos-config` from `origin/main` before each tooling install
  and every 30 minutes, skipping checkouts with local work.
- **Skip redundant Cursor downloads**: Only run the Cursor installer when its
  pinned release is not already active.

## [3.15.12] - 2026-09-26

- **Idle-aware T3 Code deployment**: Queue container image updates and restarts
  behind sustained idle, and apply them with `t3code-deploy-when-idle` only
  after active turns and pending tasks clear, so updates no longer interrupt
  running agent work.
- **Fix idle gate on deploy retry**: Re-check activity on every restart attempt,
  including the retry after a deployment that failed health verification, so a
  leftover `applying` marker cannot bypass the idle gate while tasks are active.

## [3.15.11] - 2026-09-23

- Include the T3 child-memory guard launcher in the inner image store so its
  systemd timer can execute after deployment.

## [3.15.10] - 2026-09-23

- Add a 5-second T3 child-process memory guard. It terminates an oversized
  provider/tool process before it can exhaust the shared service cgroup, while
  leaving the server process and other work running; the existing server
  health recovery remains the fallback.

## [3.15.9] - 2026-09-23

- Run the WSL WinCLI install before Codex Desktop migration can end Home
  Manager activation early while the desktop app is open.

## [3.15.8] - 2026-09-23

- Install the sbroenne WinCLI for both WSL hosts, available to Codex from WSL
  and Windows desktop sessions without an always-running service.

## [3.15.7] - 2026-09-23

- Keep the existing D-Bus implementation on WSL hosts so live NixOS switches
  are not blocked by the D-Bus switch inhibitor.

## [3.15.6] - 2026-09-23

- Repair Claude Code's recursive npm launcher by installing the matching
  platform executable directly and verifying it before use. Replace CLI
  shims atomically so existing links are not overwritten, and bound version
  probes so a broken launcher cannot stall automatic updates.

## [3.15.5] - 2026-09-23

- Ignore completed turns and old pending-start rows when deciding whether
  T3 maintenance can proceed. After five consecutive unhealthy checks, the
  server monitor performs one recovery even when activity state is stale or
  unknown, with a cooldown before another attempt. Measure memory even when
  the web interface is already unavailable.

## [3.15.4] - 2026-09-22

- Keep T3 release validation variables local so promotion cannot retarget the
  active release to a temporary staging directory. Migrate an existing staged
  installation to a verified versioned release during maintenance.

## [3.15.3] - 2026-09-22

- Restore the T3 Code web interface after npm replaced the package files used
  by a running server. Stage future T3 releases in versioned directories,
  install the native package explicitly, validate the browser bundle, and
  switch only new launches. Use the image's Python for native npm builds.
- Retry deferred tool updates as soon as T3 becomes idle, while preserving the
  active session and its queued restart. Check both the web page and the API
  environment endpoint; report degraded container health without killing
  active work.
- Remove the unused `t3code-pair` helper from the image and persistent home.
- Prefer image tools over stale user shims in T3 services and maintenance.

## [3.15.2] - 2026-09-21

- Connect the armored-armadillo WSL worker to the main T3 web client through a
  dedicated, Access-protected Cloudflare tunnel instead of T3 Connect. Add
  guarded two-minute self-healing for the worker and connector; both start with
  the NixOS WSL system and require no Windows scheduled task.
- Add an idempotent Cloudflare tunnel provisioner that reconciles the named
  tunnel, exact DNS record, loopback ingress, Access coverage, and private
  connector token without placing credentials in the Nix store.

## [3.15.1] - 2026-09-21

- Include GNU Make in the managed agent-CLI maintenance runtime so T3's
  Linux platform package can build its `node-pty` fallback when npm has no
  prebuilt binary for the current Node.js ABI.

## [3.15.0] - 2026-09-21

- Add a reusable `ghostship.host.roles.t3worker` role and `modules/agent-worker`
  platform so a Windows/WSL2 desktop joins the T3 web interface as its own
  environment. Each worker runs a persistent `t3 serve` system service, reaches
  the fleet through T3 Connect, and keeps independent projects, threads,
  providers, files, and execution.
- Install T3 and every supported provider CLI (Codex, OpenCode, Claude, Cursor,
  Gemini, Grok, and optional Antigravity ACP) through the existing agent
  maintenance service, and restart the worker only when an installed version
  changes. Provider instances are seeded only when the worker has no settings.
- Keep workers standalone: they receive only this repository's small skill set
  under `home/config/skills/` and the repo-local `home/config/AGENTS.md` with
  WSL2-specific guidance. The `ghostship-agent` catalog is not installed,
  cloned, or executed on worker hosts.
- Retire OpenChamber, the Synara T3 Code container, and the ChatGPT/Codex
  workstation: remove their modules, packages, workflow, tests, and docs, and
  quarantine their `/srv/apps` state, containers, images, units, and dashboard
  entries through `modules/self-hosted/cleanup.nix`. Keep the T3 Code Codex
  provider.
- Fix `checks.nix` referencing the already-removed `podman-synara` unit, which
  had broken host evaluation and CI.
- Clean retired agent artifacts from WSL2 user homes, including Paseo, Agent
  Deck, the WSL OpenCode desktop server, old OpenChamber user units, and
  `.openchamber` state.

## [3.14.6] - 2026-09-21

- Restore the managed Ollama Cloud and OpenRouter API keys to the T3 Code
  container environment so OpenCode's environment-backed provider
  configuration authenticates after container replacement or restart.

## [3.14.5] - 2026-09-21

- Run T3's Antigravity browser-suppression preflight with the pinned Node
  runtime instead of re-invoking the packaged T3 executable with unsupported
  Node flags.

## [3.14.4] - 2026-09-21

- Complete the Antigravity ACP compatibility bridge by returning the pinned
  1.1.1 initialization descriptor immediately and suppressing the agent's
  delayed duplicate response. This breaks the T3/agent initialization
  deadlock while leaving all authenticated session traffic on the real agent.

## [3.14.3] - 2026-09-21

- Bridge Google Antigravity's ACP initialization ordering so T3 Code can
  complete its local health check and start sessions after a server restart.
  The bridge injects the required `initialized` notification, then suppresses
  the duplicate notification from the client.

## [3.14.2] - 2026-09-21

- Make the Antigravity ACP launcher select the native ARM64 harness itself.
  T3 Code sanitizes provider child environments, so relying on a caller-supplied
  `ANTIGRAVITY_HARNESS_PATH` could relaunch the staged x86_64 helper under QEMU
  and fail session startup with a generic ACP transport error.

## [3.14.1] - 2026-09-21

- Make T3 Code's agent maintenance resolve current npm releases online and
  verify the installed manifests, so a cached or otherwise stale T3, Codex, or
  Claude CLI is a visible maintenance failure rather than a false success.
- Include the OpenSSL certificate directory required by Cursor's Node runtime.

## [3.14.0] - 2026-09-20

- Run Tdarr automatically on chill-penguin with one CPU transcode worker, folder watch, scan on start, and atomic replacement after validation.
- Publish Tdarr on Homepage and Muximux at `tdarr.ghostship.io` with Cloudflare Access protection.
- Reconcile original-language metadata from Radarr and Sonarr so unrelated dubs can be removed without guessing from filenames or stream order.

## [3.13.2] - 2026-09-20

- Wrap the current native T3 CLI with its image-provided GCC runtime library
  path. T3 0.0.42 on ARM64 requires `libatomic.so.1`; keep that path scoped to
  T3 so project-pinned Nix commands still run with clean loader settings.

## [3.13.1] - 2026-09-20

- Snapshot Chill Penguin's dedicated `/srv` Btrfs subvolume when seeding
  Synara. Snapshotting the parent root omitted nested subvolume contents and
  prevented the initial migration from finding the T3 Code state.

## [3.13.0] - 2026-09-20

- Add the independent Synara T3 Code container at `synara.ghostship.io`, with
  separate home, workspace, nested Docker, Nix store, health supervision,
  dashboard registration, Cloudflare routing, and backup coverage.
- Seed Synara once from a crash-consistent Btrfs snapshot of T3 Code's live
  home, workspace, and nested Docker state. The reflink migration preserves
  transferable provider logins, configuration, conversations, worktrees, and
  project files without stopping or restarting T3 Code.

## [3.12.3] - 2026-09-18

- Run the Antigravity `localharness_external` helper natively on ARM64 instead
  of under QEMU. Emulation corrupted its Go runtime and aborted long turns with
  "Harness process exited unexpectedly (WS close code 1006)". The x86_64 ACP
  server stays emulated because Google's binary aborts on 16 KiB pages.
- Stage the matching native harness from the official registry in the automatic
  updater, and fail the offline probe when a runtime harness is not native.

## [3.12.2] - 2026-09-17

- Define the `nobody`/`nogroup` account in the T3 container image so Google's
  Antigravity ACP harness can drop privileges for sandboxed tool work instead
  of aborting the turn.
- Fail the offline Antigravity ACP probe closed when that sandbox account is
  absent.

## [3.12.1] - 2026-09-17

- Include the agy updater integrity tests in automatic unittest discovery.

## [3.12.0] - 2026-09-17

- Detect sustained T3 process memory growth or memory pressure and restart only when idle, with a 30-minute cooldown and diagnostic samples. Ignore deleted threads and superseded pending requests in maintenance idle checks.

## [3.11.1] - 2026-09-17

- Raise the T3 service memory budget to 24 GiB soft / 32 GiB hard for the server and its child agents, preventing repeated provider and Git timeouts from cgroup memory throttling.

## [3.11.0] - 2026-09-15

- Add persistent Grok Build CLI installation and update hooks for the T3 container, with device authentication and T3 provider setup instructions.

## [3.10.2] - 2026-09-15

- Install and automatically update the official `agy` terminal CLI in the T3 container, with checksum verification and persistent storage.

## [3.10.1] - 2026-09-14

- Disable OpenChamber and its deployment timer on chill-penguin while retaining
  its declaration and persistent data for later restoration; pause its uptime
  monitor and retain monitoring history.
- Restore Homepage, Plex, NZBGet, qBittorrent, Sonarr, Radarr, and Prowlarr
  as top-level Muximux desktop tabs after the registry migration misplaced them.

## [3.10.0] - 2026-09-08

- Make T3 Code installable in Android Chrome with a named standalone manifest,
  Android launcher icons, and credentialed manifest fetching behind Cloudflare.
- Preserve installation support across T3 updates and show a reconnect screen
  offline without caching private workspace data or old application bundles.

## [3.9.1] - 2026-09-15

- Delegate shared agent instruction generation and installation to
  `ghostship-agent`, which owns the `.agents` guidance and delivery defaults.

## [3.9.0] - 2026-09-08

- Reapply T3's shared Ghostship agent tooling and native browser
  through persistent bootstrap, server-start, doctor, and post-update hooks.
- Automatically update Antigravity from the official ACP registry, preserving
  the Asahi-compatible runtime and activating only after an offline ACP check.
- Attempt each T3/provider update independently and queue idle restarts after
  partial updates or Ghostship package changes.
- Use Cloudflare sign-in for T3 browser access without a second pairing prompt,
  with an internal gateway and a loopback-only T3 backend.

## [3.8.3] - 2026-09-08

- Share installed Ghostship skills and tools across T3 Code providers, preserve
  provider plugins, and add repeatable container setup and CI validation.
- Reduce agent instructions to short workflow rules and task-specific references;
  install and apply Matt Pocock's `writing-for-agents` skill.


## [3.8.2] - 2026-09-08

- Space ordinary container restart attempts by 30 seconds so brief boot-time
  DNS failures do not exhaust systemd's rapid-start limit.
- Document persistent T3 Code deployment so reboot keeps the deployed service.

## [3.8.1] - 2026-09-08

- Run Antigravity's official x86 ACP agent through container-local QEMU on
  ARM64, avoiding Google's 4 KB allocator assertion on Asahi's 16 KB pages.
- Add an offline ACP handshake probe that exercises initialization without
  requiring a Google login or sending a model request.

## [3.8.0] - 2026-09-08

- Restore T3 Code alongside OpenChamber with independent project copies,
  persistent systemd user services, nested Docker, and an isolated Nix store.
- Enable native Codex/OpenAI, OpenCode, and Google's official Antigravity ACP
  agent; keep initial provider sign-in separate from container health.
- Register T3 Code for dashboards, Cloudflare ingress, monitoring, and backups.

## [3.7.5] - 2026-09-08

- Publish Muximux settings atomically with their PHP access guard, preventing
  concurrent reads from observing its legacy partial header rewrite.
- Use its static favicon for health checks so routine probes do not trigger
  GitHub branch refreshes or configuration writes.
- Remove the retired Paseo dashboard alias and correct Chaptarr ingress docs.

## [3.7.4] - 2026-09-08

- Allow Kuma's populated monitor/stat login burst within a bounded Engine.IO
  polling limit so provisioning remains repeatable after initial setup.
- Monitor pyLoad's direct public robots endpoint instead of its favicon
  redirect, avoiding false alarms while retaining strict HTTP status checks.

## [3.7.3] - 2026-09-08

- Supply Kuma's required empty monitor conditions for HTTP, TCP, and heartbeat
  provisioning instead of sending an implicit null value.
- Monitor the primary OpenChamber HTTP endpoint through the service registry.
- Omit Seerr's legacy enable query parameter only for an empty selection,
  satisfying its validator while preserving existing enabled libraries.

## [3.7.2] - 2026-09-08

- Keep the shared Podman network setup active after success so simultaneous
  container starts do not repeatedly run it and hit systemd's start limit.
- Keep both agent containers outside shared hard startup dependencies so a
  network-setup unit update cannot stop active OpenChamber work.
- Run ntfy on unprivileged internal port 8080 and synchronize its tunnel,
  dashboard, health check, publisher, and monitoring references.
- Use Plex's installed curl client for readiness checks instead of absent wget,
  avoiding false health failures and unnecessary container restarts.
- Support the released Seerr library-setup API as well as its newer API,
  preserving selected libraries when retrying incomplete provisioning.

## [3.7.1] - 2026-09-08

- Preserve chill-penguin's running D-Bus implementation across the nixpkgs
  refresh so fleet activation does not require rebooting the active agents.

## [3.7.0] - 2026-09-08

- Declare service hostnames, origins, and dashboard metadata with each container;
  automatically reconcile Cloudflare routes/DNS and both dashboards while
  preserving unrelated entries and Google Access policies.

- Add Uptime Kuma, authenticated Android ntfy notifications, and Seerr with
  approval-required requests using existing Plex/Sonarr/Radarr settings.
- Add encrypted Restic backups, isolated restore checks, retention, stale-job
  alerts, and a recent-backup gate for automatic container updates. Pin the
  current MariaDB image digests for reviewed engine migrations.
- Refresh coordinated Nix inputs; adapt Home Manager SSH option names without
  changing policy, and use the compatible nixpkgs ragenix CLI.
- Retain the compatible Apple Silicon input until vendor firmware is rebuilt
  from macOS; the newer input requires a firmware archive this host lacks.
- Render application configuration at service startup, preserve native secret
  values in Podman env files, require critical secrets, and write configs atomically.
- Add readiness notifications, network/NAS/database ordering, and non-destructive
  retirement quarantine while preserving the active agent environment.
- Stabilize OpenChamber with isolated immutable tool generations, activity-aware
  promotion, candidate validation, and recoverable image deployments. Count
  pending goal audits as active work, preserve quiet detached terminals, and
  observe provider retries without aborts. Retain image dependencies for rollback
  and recover staging permissions after interrupted validation.
- Raise the configurable goal continuation cap to 1,000 while retaining token
  budgets and explicit goal termination controls; include the configured limit
  in generation identity so changed limits take effect.
- Preserve the live Codex workstation and reconcile its service registry.
- Add fleet CI and weekly validated input-update PRs; system upgrades consume
  the committed lock file. Correct stale inventory docs and document recovery.

## [3.6.1] - 2026-09-07

- **Notification targets**: Capture task routes across the upstream RPC read
  loop and coalesce repeated completion alerts by upstream notification ID.
- **Phone rotation**: Keep the mobile drawer and visual-viewport sizing on touch
  phones in landscape so browser chrome and the keyboard cannot clip controls.

## [3.6.0] - 2026-09-07

- **Background notifications**: Persist per-device Web Push subscriptions and
  VAPID keys, encrypt completion alerts, wake the service worker for closed-tab
  delivery, and open the app from notification clicks. Report registration
  failures with a retry action.
- **Idle upgrades**: Check the signed ChatGPT Linux repository every 15 minutes
  and allow activation after 15 minutes without browser input, while protecting
  active tasks, recordings, open terminals and dialogs.
- **Project selection**: Disable folder selection during navigation so a quick
  click cannot select the previous directory. Document the OpenChamber project,
  Git authentication and Nix profile migration.
- **Mobile project screen**: Fit the inner zoomed frame to the visible viewport
  and remove the desktop suggestion overlap so project headings and composer
  controls stay separate below Android browser chrome.
- **Browser verification**: Exercise encrypted push payloads, stopped-worker
  notifications, multi-device focus and update deferral, plus the folder-loading
  race. Include a local speech fixture tool for microphone acceptance.

## [3.5.0] - 2026-09-07

- **ChatGPT Linux workstation**: Restore the web-native desktop renderer using
  the official ARM64 Linux application and its native runtime in the existing
  Nix/systemd OCI workstation, with persistent Nix, Docker, home and workspace.
- **Application updates**: Authenticate OpenAI's signed package index, build and
  smoke-test isolated candidates, queue idle activation and restore the previous
  generation after failed startup. Refresh browser assets on transport changes.
- **Browser compatibility**: Support sandboxed Linux preloads, preserve binary
  IPC payloads and initialize the upstream renderer's application version.
- **Web controls**: Use upstream web menus, keep project actions visible, refresh
  chunked state updates and reconnect without replaying an application backlog.
- **Embedded browser**: Resize pages to their panel, preserve keyboard modifiers,
  and keep typing focused through cursor overlays and application shortcuts
  without announcing navigation on each keystroke.
- **Bundled plugins**: Make runtime copies writable so Linux plugin variants can
  be materialized from sealed Nix resources.
- **Restart reliability**: Keep the updater alive through its own restart and
  health checks, and defer automatic activation while browser tabs are connected.
- **Chat startup**: Forward desktop tool-server configuration to each persistent
  app-server thread and provide the Linux sandbox helper.
- **Folder picking**: Keep file dialogs above clipped project modals while
  preserving the parent dialog during selection.
- **Recovery checks**: Require renderer heartbeats and roll back failed service
  starts as well as failed health checks.
- **Mobile layout**: Keep navigation in a drawer and size the app to the visible
  viewport so the composer stays reachable with browser chrome and keyboards.
- **Session synchronization**: Refresh project state in place across browsers,
  preserving the current conversation and unsent draft during project changes,
  and isolate transport channels between tabs sharing browser storage. Preserve
  Electron window identity so native state broadcasts include the app window.
- **Browser startup**: Compress large HTTP and WebSocket payloads, route request
  replies to their originating tab, and avoid resending the full startup
  snapshot for project updates. Relay complete native chunked messages and
  acknowledge them independently of the hidden renderer to keep state updates flowing.
- **Authenticated app installation**: Include access cookies when Chrome fetches
  the web app manifest behind Cloudflare Access.

## [3.4.6] - 2026-08-12

- **OpenChamber deployment policy**: Let operator-approved host deployments
  apply changed OpenChamber images without waiting for session idle, while
  preserving idle gates for automated tool updates and health recovery.

## [3.4.5] - 2026-08-12

- **Gluetun benchmark reliability**: Use Gluetun's DNS server for candidate
  containers, benchmark against Hetzner's bounded download endpoint, and
  invalidate cached winner speeds when the benchmark source changes.
- **RomM migration recovery**: Allow binary-logged MariaDB migrations to manage
  functions and triggers, wait for database readiness, disable Gunicorn's
  unwritable control socket, and rate-limit failed RomM starts across a full
  day so a migration error cannot cause a rapid restart storm.
- **Recyclarr update recovery**: Follow the supported Recyclarr 8 major image
  tag after upstream removed `latest`, restoring Podman registry auto-update
  checks and moving daily synchronization off the stale 8.3.2 release.

## [3.4.4] - 2026-08-07

- **Codex live acceptance reliability**: Keep repeated readiness checks on the
  existing browser session so they do not discard Chrome's one-shot install
  event, and test the terminal without requiring pre-existing task history.

## [3.4.3] - 2026-08-07

- **Codex Android install recovery**: Restore the browser-owned install offer
  when a shared native-renderer refresh replaces its DOM node.

## [3.4.2] - 2026-08-07

- **Codex auxiliary-window recovery**: Make opaque bridged desktop windows
  accessible dialogs and let Escape close them so a stale About or New Window
  surface cannot permanently intercept browser input.
- **Codex multi-device menu isolation**: Keep the keyboard-shortcuts modal on
  the browser device that requested it instead of opening or replaying it on
  every connected device.
- **Codex UI surface coverage**: Add a real-Chrome desktop and Android sweep for
  application menus, native windows, project dialogs, primary screens, every
  settings screen, and safe dropdown controls.

## [3.4.1] - 2026-07-27

- **Codex Android prompt layout**: Stack the Chrome install offer beneath the
  notification permission offer so both remain readable and clear of the
  native Codex pet on small screens.

## [3.4.0] - 2026-07-27

- **Codex Android install offer**: Match OpenChamber by capturing Chrome's
  `beforeinstallprompt` event and presenting a persistent native-styled Install
  or Dismiss offer. Serve the manifest with its standard media type and verify
  the real Chrome event in the live acceptance suite.

## [3.3.13] - 2026-07-26

- **Codex full-screen fallback**: Keep browser-local full-screen state
  deterministic when Chrome declines the native Fullscreen API, and cover both
  entering and leaving full screen in real-browser tests.

## [3.3.12] - 2026-07-26

- **Codex per-device full screen**: Handle the native full-screen menu action
  in the invoking browser so a closed or second device cannot leave Electron's
  global window state out of sync with tab-local browser full screen.
- **Codex acceptance cleanup**: Use physical project-action clicks and exact
  scheduled-task controls, and tolerate an already-visible persistent pet.

## [3.3.11] - 2026-07-26

- **Codex pet overlay usability**: Make the transparent native pet surface
  click-through in browsers so it remains visible without blocking composer or
  model-picker controls.
- **Codex repeatable browser tests**: Verify that a persistent pet remains
  visible without obstructing later controls across repeated fresh-profile
  acceptance runs.

## [3.3.10] - 2026-07-26

- **Codex auxiliary window lifecycle**: Give opaque browser-bridged desktop
  windows an accessible close control so About does not remain above and block
  the native app after it is opened.
- **Codex live browser coverage**: Exercise the deployed app from fresh
  Android and desktop Chrome profiles, including installability, notifications,
  menus, projects, shared state, Ollama models, terminal, About, pet, and full
  screen.

## [3.3.9] - 2026-07-26

- **Codex project picker browser fix**: Mount the bridged folder picker inside
  the upstream project modal so capture-phase outside-click handling cannot
  dismiss project creation.
- **Codex installable app parity**: Match OpenChamber's install metadata with
  separate standard and maskable Android icons, an Apple touch icon, mobile app
  metadata, language, and related-app policy.
- **Codex browser acceptance tests**: Add real-Chrome regression coverage for
  project picker containment and live full-function/PWA acceptance.

## [3.3.8] - 2026-07-26

- **Codex project removal propagation**: Recognize the native local-project
  fetch response as an authoritative sidebar-state change so removals refresh
  the shared bootstrap and every connected browser.

## [3.3.7] - 2026-07-26

- **Codex multi-device project state**: Detect project-list changes once in the
  shared gateway and send the same delayed refresh signal to every connected
  browser, including passive devices after project removal.

## [3.3.6] - 2026-07-26

- **Codex project synchronization**: Refresh every connected browser after the
  shared project list changes while preserving the completion delay that keeps
  create and remove transactions intact.
- **Codex dropdown controls**: Treat all nested trigger content as part of its
  parent button so icon-based menus remain reliable on touch and in browsers.

## [3.3.5] - 2026-07-26

- **Codex notification prompt**: Keep the browser notification permission
  prompt clear of the composer controls so model and tool dropdowns remain
  usable before the prompt is answered.

## [3.3.4] - 2026-07-26

- **Codex project creation**: Let native project creation finish before
  refreshing connected browser project state instead of interrupting it with an
  immediate reload.
- **Codex dropdown controls**: Make menu-trigger buttons own their complete
  pointer target and refresh the PWA asset cache for existing installations.

## [3.3.3] - 2026-07-26

- **Codex project picker events**: Isolate browser picker pointer events from
  the native app modal so selecting a folder cannot trigger its outside-click
  dismissal.
- **Codex project synchronization**: Reload connected browser renderers when
  the native project sidebar bootstrap changes so created and removed projects
  appear immediately on every device.

## [3.3.2] - 2026-07-26

- **Codex project folder picker**: Keep the native Create Project modal mounted
  while the browser folder picker is open so selecting a source folder returns
  to the project form instead of dismissing it.

## [3.3.1] - 2026-07-26

- **Codex project synchronization**: Keep the project bootstrap current across
  devices and expose the add-project action on touch-only browsers.
- **Codex full-screen menu**: Let the upstream menu command own the browser
  full-screen transition so one tap cannot immediately toggle it back off.

## [3.3.0] - 2026-07-26

- **Codex browser desktop contracts**: Make project folder selection tappable
  inside native modals, preserve the upstream application menu, relay native
  About and pet windows to every browser, and bridge full-screen state.
- **Codex web notifications and schedules**: Request browser notification
  permission explicitly and route desktop notifications through the PWA
  service worker so task and scheduled-run completion works on Android.

## [3.2.1] - 2026-07-26

- **Codex Browser release packaging**: Copy and validate the Browser surface
  bridge explicitly when preparing the Nix ASAR so live containers cannot
  start with Browser chrome but no page surface.

## [3.2.0] - 2026-07-26

- **Codex built-in browser**: Host Codex's expected native renderer origin,
  relay persistent browser surfaces and input through the unchanged desktop
  Browser panel, and share each tab across connected devices.
- **Codex Android app installation**: Keep the official responsive renderer
  behind a root-scoped service worker and standalone manifest, with fresh
  Chrome installability coverage for the container image.

## [3.1.4] - 2026-07-26

- **OpenChamber deployment retry safety**: Latch failed image deployments,
  preserve the idle gate across interrupted attempts, and prevent a failed
  deployment from repeatedly restarting the container.
- **OpenChamber bootstrap reconciliation safety**: Gate orphan reconciliation
  on the root-visible web service state and add unprivileged runtime checks so
  a manual bootstrap cannot rewrite active tool records.

## [3.1.3] - 2026-07-26

- **Codex native startup dependencies**: Start the user D-Bus daemon with its
  real session configuration and expose the C++ and graphics runtime libraries
  needed by the official desktop native modules on ARM.

## [3.1.2] - 2026-07-26

- **Codex ARM runtime stability**: Give the persisted XDG configuration tree
  back to the Codex user during container setup so Electron can initialize its
  crash database instead of repeatedly terminating on `chill-penguin`.

## [3.1.1] - 2026-07-26

- **Codex package evaluation**: Permit the versioned official desktop package
  as the Codex container's sole unfree dependency.

## [3.1.0] - 2026-07-26

- **Official Codex desktop web port**: Replace `0xcaff/codex-web` with a
  versioned bridge around the signed official Codex desktop renderer, preload,
  main process, Linux Electron runtime, terminal, and persistent app server.
- **Shared browser and mobile runtime**: Fan one native app host out to
  multiple browser devices, add confined server-side file dialogs and uploads,
  and ship a Chrome-installable Android PWA.
- **Durable compatibility and operations**: Verify upstream signatures and IPC
  contracts, preserve idle-gated updates and rollback, supervise Electron and
  Xvfb cleanly, and keep only tool-capable Ollama.com models in the picker.

## [3.0.6] - 2026-07-26

- **T3 server browser inheritance**: Attach the CloakBrowser route to the T3
  server unit that spawns provider sessions.

## [3.0.5] - 2026-07-26

- **T3 provider browser environment**: Propagate the internal CloakBrowser URL
  into the T3 server process so Codex and OpenCode sessions inherit it.

## [3.0.4] - 2026-07-26

- **T3 Code CloakBrowser routing**: Configure T3-launched agents to use the
  internal CloakBrowser service so the installed browser tools work without
  per-session setup.

## [3.0.3] - 2026-07-26

- **T3 Code CloakBrowser tools**: Put the preserved Ghostship `agent` and
  `ghostship-cloakbrowser` launchers on the container user's PATH so T3-launched
  Codex and OpenCode sessions can manage CloakBrowser without `agent-browser`.

## [3.0.2] - 2026-07-26

- **OpenChamber interruption prevention**: Decouple container deployments from
  unrelated repository revisions, apply changed images only after sustained
  OpenChamber-reported idle, and run bootstrap hooks before the single web
  service start.
- **OpenChamber session resilience**: Bound provider retries and timeouts,
  enable tool-output pruning during compaction, reconcile orphaned tool calls,
  require consecutive monitor failures, and add restart-source auditing.

## [3.0.1] - 2026-07-26

- **T3 Code migration cleanup**: Remove the retired Paseo npm package during
  every container setup, including when all replacement tools are already
  current and package maintenance is skipped.

## [3.0.0] - 2026-07-26

- **T3 Code replacement**: Replace the Paseo daemon and web UI with upstream
  T3 Code at `t3code.ghostship.io` on its native port `3773`, while preserving
  the existing workspace, credentials, nested Docker, Nix, user services,
  Codex, OpenCode, Antigravity, and Ollama Cloud integration.
- **T3 Code operations**: Add project registration, one-time remote pairing,
  provider-aware health checks, idle-gated updates, and last-good settings
  recovery for the new server.

## [2.6.2] - 2026-07-26

- **Paseo Codex ripgrep compatibility**: Replace Codex's bundled glibc-path
  `rg` with the Nix-packaged ripgrep after container setup and every Codex
  update so agent shell commands do not fail on the minimal image.

## [2.6.1] - 2026-07-26

- **Paseo Ollama provider routing**: Route derived Ollama Codex threads through
  the authenticated loopback endpoint instead of allowing Paseo's Codex adapter
  to reset them to the default OpenAI API.

## [2.6.0] - 2026-07-26

- **Paseo Ollama Codex provider**: Add a distinct `Codex (Ollama Cloud)`
  provider that uses the supported `ollama launch codex` flow through an
  authenticated loopback proxy, with a refreshed catalog of tool-capable
  ollama.com models.

## [2.5.0] - 2026-07-26

- **Paseo agent tooling**: Enable Paseo's MCP server, agent tool injection, and
  browser-tool broker while preserving the rest of the persisted daemon config.
- **Paseo Ollama access**: Install the Ollama CLI and project the existing
  ollama.com API key into the container as `OLLAMA_API_KEY`.
- **Paseo hostname**: Give the container the stable
  `paseo.ghostship.io` hostname instead of a generated container ID.

## [2.4.9] - 2026-07-26

- **Retired skill lock cleanup**: Remove retired skills from the XDG-state
  global skill lock used by agent maintenance, preventing `brainstorming` from
  being reinstalled after cleanup.

## [2.4.8] - 2026-07-22

- **Paseo web UI patch quoting**: Use a single-line JavaScript replacement and
  repair the malformed escaped-newline form left by version 2.4.7 before the
  daemon starts.

## [2.4.7] - 2026-07-22

- **Paseo persisted bootstrap fix**: Apply the web UI connection-hint
  compatibility patch on every daemon start, including when the persisted agent
  tools are already current and cold bootstrap skips package maintenance.

## [2.4.6] - 2026-07-22

- **Paseo web UI bootstrap**: Patch Paseo's same-origin connection hint to
  include the default HTTP or HTTPS edge port, preventing the bundled client
  from rejecting a portless hostname and falling back to `localhost:6767`.

## [2.4.5] - 2026-07-22

- **Paseo reverse proxy connection**: Trust the loopback and Ghostship Podman
  proxy networks so the bundled HTTPS web UI derives a secure `wss://`
  connection from Cloudflare's forwarded protocol.

## [2.4.4] - 2026-07-22

- **Paseo user services**: Start the persistent user D-Bus from its packaged
  session configuration so user units and Secret Service remain reachable.

## [2.4.3] - 2026-07-22

- **Paseo maintenance safety**: Defer package mutation while Paseo reports
  active or unknown work, and add `ps` for managed-provider process
  reconciliation plus bzip2 support for bundled speech model extraction.

## [2.4.2] - 2026-07-22

- **Paseo Antigravity migration**: Treat a persisted `agy` binary as installed
  only when it can execute, so upgrades automatically replace the unusable raw
  aarch64 binary from the initial deployment with the managed glibc wrapper.

## [2.4.1] - 2026-07-22

- **Paseo cold bootstrap**: Assign first-created npm and XDG directories to the
  unprivileged Paseo user before tool installation, and launch the official
  dynamically linked aarch64 Antigravity binary through Nix's glibc loader.

## [2.4.0] - 2026-07-22

- **Self-hosted Paseo**: Add a repo-built systemd Podman image with Paseo,
  Codex, OpenCode, and Antigravity, persistent user services, Docker and Nix
  state, activity-gated four-hour updates and recovery, Quick Tunnels, config
  validation with rollback, clean shutdown, and Homepage/Muximux entries.
- **Paseo exposure contract**: Listen on the internal network at port 6767
  without an application password, leaving the external route and mandatory
  authentication boundary to Cloudflare Access.

## [2.3.0] - 2026-07-22

- **Codex Android installation**: Patch every pinned or automatically updated
  Codex Web generation at runtime with a complete standalone manifest, 192px
  and 512px maskable icons, mobile web-app metadata, and a root-scoped service
  worker so Chrome on Android offers the same install flow as OpenChamber.

## [2.2.1] - 2026-07-22

- **Codex Ollama credential handling**: Keep the Ollama.com authorization
  header out of catalog-refresh process arguments, and let app-server protocol
  helpers discover the managed Unix socket without caller-provided environment.

## [2.2.0] - 2026-07-22

- **Self-hosted Codex Web**: Add a systemd-based Codex container with a
  persistent app server, disposable `codex-web` bridge, persistent user
  services, Docker and Nix state, activity-gated four-hour updates, guarded
  recovery, clean shutdown, Quick Tunnels, and config validation with rollback.
- **Ollama.com models**: Project `OLLAMA_API_KEY` through the secret catalog,
  proxy cloud inference over loopback, and add only models advertising tool
  capability to the Codex Web picker.

## [2.1.128] - 2026-07-22

- **Autoreview skill retirement**: Remove the repo-managed `autoreview` skill
  and its Codex configuration, and clean stale installations from develop
  hosts.

## [2.1.127] - 2026-07-14

- **OpenChamber systemd shutdown targets**: Install systemd's upstream halt,
  shutdown, final, unmount, and halt-service unit chain in the minimal image's
  active unit search path so Podman's `SIGRTMIN+3` stop signal can shut down
  instead of waiting for the outer timeout and forcing a container-wide
  SIGKILL.

## [2.1.126] - 2026-07-14

- **OpenChamber bounded shutdown**: Cap the web and user manager at 10 seconds
  and the Docker and Nix daemons at 30 seconds while preserving systemd's
  longer stop allowance for package updates and bootstrap hooks that mutate
  persistent state. Nix shutdown now includes connection and build workers.
  Podman's 180-second aggregate stop window leaves enough headroom for either
  path, the host unit allows 210 seconds, and explicit `shutdown.target`
  ordering ensures the container services receive their stop jobs without a
  container-wide SIGKILL.

## [2.1.125] - 2026-07-14

- **OpenChamber initial health probe**: Treat the brief interval before the
  container system manager accepts unit queries as startup rather than a
  failed health check, avoiding false failed transient health units during
  deployment.

## [2.1.124] - 2026-07-14

- **OpenChamber persistent store seeding**: Trust paths copied directly from
  the host's local Nix store when incrementally seeding the isolated container
  store, including locally built image closures that have no binary-cache
  signature.

## [2.1.123] - 2026-07-14

- **OpenChamber startup health gate**: Treat activating container setup,
  bootstrap, and web startup as healthy for up to 20 minutes of container
  system-manager uptime so long first-start tooling builds cannot exhaust the
  Podman health start period and enter a container kill/restart loop. Root
  health probes now use absolute Nix-store tool paths. Normal
  restarts now skip tool maintenance when the persisted OpenChamber and
  OpenCode binaries already exist, start the web service before project hooks,
  run bootstrap and before-web hooks in the background, and queue one
  idle-gated maintenance restart after those hooks finish. The container now
  uses an isolated persistent Nix store seeded incrementally from the image
  closure and served through a root-owned internal `nix-daemon`, so
  container-built agent packages survive image replacement without exposing
  the host's primary store to container writes.

## [2.1.122] - 2026-07-14

- **OpenChamber idle-gated tool updates**: Queue OpenChamber and OpenCode tool
  restarts only after an installed version changes, and apply them through a
  separate timer only when OpenChamber's aggregate session activity reports
  that all work is idle. The web monitor now applies the same gate before
  restarting an active but unhealthy runtime, and the outer container health
  policy observes the same gate before killing the container. The web service
  now throttles above 32 GiB and caps its workload at 40 GiB with a
  continue-on-OOM policy, preventing a runaway child process from escalating
  into a host-wide OOM and full OpenChamber restart.
## [2.1.121] - 2026-07-08

- **OpenChamber apply command fix**: Preserve root setuid ownership on the
  container-local `sudo` binary so `openchamber-apply-config` can restart
  `openchamber-web.service` through its narrow sudoers rule as the
  unprivileged `openchamber` user.

## [2.1.120] - 2026-07-08

- **OpenChamber Ghostship agent compatibility**: Seed `/home/openchamber/tools`
  from `/workspace/ghostship-agent/tools` when present so installed
  `ghostship-agent` command wrappers keep resolving their repo-local support
  scripts after container rebuilds.

## [2.1.119] - 2026-07-08

- **OpenChamber project runtime support**: Run startup project hooks as the
  `openchamber` user, add `openchamber-user-units` for persisted user
  systemd services and timers, and document the supported hook, config apply,
  recurring job, and tool auto-update contracts.

## [2.1.118] - 2026-07-08

- **OpenChamber Quick Tunnels**: Replace the in-container Caddy wildcard app
  proxy with Cloudflared Quick Tunnel support and an `openchamber-tunnel`
  helper for exposing OpenChamber-launched loopback web apps through ephemeral
  `trycloudflare.com` URLs.

## [2.1.117] - 2026-07-08

- **OpenChamber sudoers image build**: Remove packaged sudo defaults before
  writing the container-local sudoers and PAM files used by
  `openchamber-apply-config`.

## [2.1.116] - 2026-07-08

- **OpenChamber config apply command**: Add `openchamber-apply-config` for
  non-root OpenChamber JSON validation, native OpenCode config validation,
  controlled web-service restart, health verification, and rollback to the
  last-good runtime config snapshot refreshed by successful
  `openchamber-web.service` starts.

## [2.1.115] - 2026-07-08

- **OpenChamber wildcard app proxy**: Add an in-container Caddy proxy and
  `openchamber-proxy` helper so OpenChamber-launched local web servers can be
  routed under `*.test.openchamber.ghostship.io` through the Cloudflare tunnel.

## [2.1.114] - 2026-07-01

- **OpenChamber Bitwarden projection**: Include Bitwarden client and password
  fields in the OpenChamber runtime secret projection.

## [2.1.113] - 2026-07-01

- **OpenChamber env projection**: Project OpenCode, OpenRouter, and GitHub
  secrets into OpenChamber and source them inside the container runtime.

## [2.1.112] - 2026-06-27

- **Gluetun endpoint fallback**: Rotate through cached PIA WireGuard fallback
  endpoints during bootstrap and let the selector run without depending on a
  healthy Gluetun container so dead VPN endpoints can self-repair.

## [2.1.111] - 2026-06-23

- **OpenChamber hook isolation**: Log failing lifecycle hooks and continue
  startup so persisted user automations cannot prevent OpenChamber from
  starting after image recreation.

## [2.1.110] - 2026-06-23

- **Codex container retirement**: Remove the self-hosted Codex Podman service,
  dashboard entries, secret projection, hosted tooling bootstrap, and
  `codex-web` flake input, and add its live container, unit, image, and
  `/srv/apps/codex` state to retired artifact cleanup.

## [2.1.109] - 2026-06-23

- **OpenChamber automation environment**: Export
  `OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation` from the container
  runtime and keep the persisted automation directory created for the
  `openchamber` user.

## [2.1.108] - 2026-06-23

- **OpenChamber user systemd runtime**: Start `user@3000.service` in the
  container image, provide the minimal user systemd targets and D-Bus user bus,
  and order OpenChamber bootstrap after the user manager is available.

## [2.1.107] - 2026-06-22

- **OpenChamber lifecycle hooks**: Add generic container bootstrap, pre-web,
  and doctor hook directories that run before OpenChamber starts, leave
  repo-installed automation units intact in the persisted home, and allow
  hook-owned system timers to run as `openchamber`.

## [2.1.106] - 2026-06-21

- **OpenChamber web monitor**: Add a container systemd monitor service and
  timer that restarts the OpenChamber web service when the UI is up but the
  managed OpenCode process is missing, and make the system service PATH stable
  for npm-installed launchers.

## [2.1.105] - 2026-06-21

- **OpenChamber tool auto-updates**: Add a container systemd timer that keeps
  OpenChamber and OpenCode installed at their latest npm versions and restarts
  the system web service only when a tool version changes.

## [2.1.104] - 2026-06-21

- **OpenChamber graceful stops**: Increase the Podman stop timeout for the
  systemd-based OpenChamber container so deployment restarts have time to shut
  down cleanly instead of falling back to SIGKILL.

## [2.1.103] - 2026-06-20

- **OpenChamber user unit cleanup**: Remove stale repo-seeded
  `ghostship-*` user systemd units from the persisted OpenChamber home so the
  repo no longer leaves installed services in the OpenChamber user manager.

## [2.1.102] - 2026-06-20

- **OpenChamber system web service**: Run the OpenChamber web process as a
  container systemd service, stop enabling the old user-level
  `openchamber.service`, stop seeding repo-managed user systemd targets, and
  clean up stale repo-managed user unit links.

## [2.1.101] - 2026-06-20

- **OpenChamber user task limit repair**: Rewrite existing persisted
  `openchamber.service` user units when they are missing the unlimited
  `TasksMax` setting.

## [2.1.100] - 2026-06-20

- **OpenChamber process limits**: Remove the Podman PID cap and set the
  generated OpenChamber system and user services to unlimited systemd tasks.

## [2.1.99] - 2026-06-20

- **OpenChamber user systemd runtime**: Run the user manager as the
  `openchamber` user with delegated cgroup control, seed a minimal user
  `default.target`, and make the OpenChamber web shim independent of service
  `PATH`.

## [2.1.98] - 2026-06-20

- **OpenChamber user manager launch**: Start the persistent `openchamber` user
  systemd manager through systemd's actual daemon path so the user service
  manager comes up inside the container image.

## [2.1.97] - 2026-06-20

- **OpenChamber systemd dependency repair**: Disable default systemd
  dependencies on the minimal container units and remove packaged Docker units
  from the boot target so OpenChamber services can start without a full NixOS
  target tree.

## [2.1.96] - 2026-06-20

- **OpenChamber user service repair**: Run the seeded OpenChamber user service
  through a stable `/home/openchamber/.local/bin/openchamber-web-run` shim,
  repair old generated units that point at stale image store paths, and extend
  the first-start health window for systemd-managed startup.

## [2.1.95] - 2026-06-20

- **OpenChamber systemd boot target**: Add explicit `default.target` and
  `multi-user.target` units to the OpenChamber image so systemd can boot the
  generated container services as PID 1.

## [2.1.94] - 2026-06-20

- **OpenChamber systemd supervision**: Replace the container's s6,
  Supercronic, webhook, and Taskfile automation stack with systemd as PID 1,
  keep `dockerd` as a root system unit, and seed OpenChamber as a user-level
  systemd service so the `openchamber` user can manage its own services and
  timers.

## [2.1.93] - 2026-06-19

- **OpenChamber agent ownership**: Stop deleting or rewriting persisted
  Ghostship agent files, Nix state, cron entries, skills links, and OpenCode
  `AGENTS.md`; only seed OpenChamber defaults when missing.

## [2.1.92] - 2026-06-19

- **OpenChamber agent state**: Stop deleting persisted `.agent-browser` and
  `.agents` state during container startup so agent tooling can be managed
  entirely from inside the container.

## [2.1.91] - 2026-06-19

- **OpenChamber persisted tools**: Stop managing `/home/openchamber/.nix-profile`
  from the image startup path and preserve persisted `.local/bin` agent links
  for tooling managed inside the container.

## [2.1.90] - 2026-06-19

- **OpenChamber PATH cleanup**: Put `/home/openchamber/.nix-profile/bin` in
  the managed runtime PATH even without Home Manager session vars, and rewrite
  migrated cron comments that still referenced the Codex container.

## [2.1.89] - 2026-06-19

- **OpenChamber profile package**: Install the seeded OpenChamber Nix profile
  as one curated `buildEnv` package to avoid package-file collisions.

## [2.1.88] - 2026-06-19

- **OpenChamber Nix profile**: Seed `/home/openchamber/.nix-profile` from the
  OpenChamber image package set instead of the Codex Home Manager activation,
  and prune the migrated `ghostship-agent-bootstrap` cron entry.

## [2.1.87] - 2026-06-19

- **OpenChamber bootstrap resilience**: Regenerate the fallback agent bootstrap
  Taskfile at startup, skip Home Manager activation when the existing profile
  already has `agent`, and keep OpenChamber running if bootstrap activation is
  incompatible with the `openchamber` user.

## [2.1.86] - 2026-06-19

- **OpenChamber bootstrap repair**: Replace a stale
  `.automation/ghostship-agent-bootstrap.Taskfile.yml` symlink with a regular
  persisted Taskfile before running the startup bootstrap.

## [2.1.85] - 2026-06-19

- **OpenChamber profile activation**: Stop creating a fake `.nix-profile`
  directory and run the persisted agent bootstrap before s6 starts so
  Home Manager recreates `.nix-profile` as the real profile link.

## [2.1.84] - 2026-06-19

- **OpenChamber session profile**: Seed a minimal
  `/home/openchamber/.nix-profile/etc/profile.d/hm-session-vars.sh` before s6
  starts OpenChamber so the web process inherits the expected Home Manager path.

## [2.1.83] - 2026-06-19

- **OpenChamber runner PATH**: Source Home Manager session variables after the
  container tool path is assembled so `/home/openchamber/.nix-profile/bin`
  remains visible to OpenChamber runners.

## [2.1.82] - 2026-06-19

- **OpenChamber runner environment**: Source Home Manager session variables
  before OpenChamber services start and pass the inherited environment through
  `su-exec` to OpenChamber, supercronic, and webhook.

## [2.1.81] - 2026-06-19

- **OpenChamber startup cleanup**: Prune migrated agent artifacts from the
  OpenChamber home and clear stale OpenChamber port run files before starting
  the supervised web service.

## [2.1.80] - 2026-06-19

- **OpenChamber OpenCode environment**: Make generated OpenCode wrappers source
  `/home/openchamber/.nix-profile/etc/profile.d/hm-session-vars.sh` when it
  exists, without requiring a Home Manager profile.

## [2.1.79] - 2026-06-19

- **Homepage service grouping cleanup**: Prune stale Codex entries from
  Homepage's Management group now that Codex belongs under Services.

## [2.1.78] - 2026-06-19

- **Agent dashboard placement**: Move OpenChamber and Codex into Homepage's
  Services group and order OpenChamber after Grimmory in Muximux.

## [2.1.77] - 2026-06-19

- **RSS Bridge retirement**: Remove RSS Bridge from the active self-hosted
  stack, Homepage, and Muximux, and add cleanup for its Podman unit, container,
  image, and `/srv/apps/rss-bridge` config.

## [2.1.76] - 2026-06-19

- **OpenChamber self-hosted service**: Add a repo-built OpenChamber image for
  `chill-penguin` with s6-managed Docker-in-Docker, OpenChamber, Supercronic,
  and webhook services, persistent `/home/openchamber` state under
  `/srv/apps/openchamber`, OpenCode installed for OpenChamber to start, no UI
  password configuration, and Muximux updated to make OpenChamber the primary
  agent link while moving Codex into the dropdown.

## [2.1.75] - 2026-06-15

- **Codex user tool path**: Expose mutable Codex-user tooling only through
  `/home/codex/.local/bin`, keep npm-backed agent installs under internal
  `ghostship-agent-tools` state, and initialize the standard XDG user
  directories in the hosted Codex image.

## [2.1.74] - 2026-06-08

- **Codex container Nix logs**: Make `/nix/var/log/nix` writable by the
  `codex` user in the Codex image so rootless Nix can create derivation build
  logs while building Home Manager activations.

## [2.1.73] - 2026-06-08

- **Codex container Nix store**: Build the Codex image with a populated Nix
  database and make the image-owned `/nix/store` plus `/nix/var/nix` writable
  by the `codex` user so rootless Nix and Home Manager activations produce
  system-visible `/nix/store` paths instead of falling back to a per-user
  chroot store.

## [2.1.72] - 2026-06-08

- **Codex startup directory**: Start the Codex web service from `/home/codex`
  and set the container working directory to the persisted Codex home.

## [2.1.71] - 2026-06-08

- **Codex automation ownership**: Stop seeding the
  `ghostship-agent-bootstrap` Taskfile and cron entry from the NixOS container
  config. `nixos-config` now only provides the base image, `agent-browser`, and
  persistent Supercronic/Taskfile framework; `/workspace/ghostship-agent` owns
  its repo-specific persistent bootstrap through Home Manager activation.

## [2.1.70] - 2026-06-08

- **Codex automation agent repo bootstrap**: Seed the existing Codex
  Supercronic and Taskfile automation with a managed
  `ghostship-agent-bootstrap` task that builds and activates
  `/workspace/ghostship-agent#homeConfigurations.codex.activationPackage` for
  the `codex` user. This keeps mutable shared agent tooling and skills outside
  the image while avoiding changes to the Codex container entrypoint/setup
  path; `agent-browser` remains in the base image.

## [2.1.69] - 2026-06-08

- **OpenCode agent tooling fallback**: Teach Codex agent maintenance to fall
  back to OpenCode's architecture-specific npm package when `opencode-ai`
  selects an incompatible platform package, and make the flake-installed
  `opencode` wrapper tolerate that fallback binary layout in Nix images that
  do not expose the glibc loader at the fallback binary's FHS path.

## [2.1.68] - 2026-06-08

- **Codex agent tooling flake installer**: Add
  `.#install-codex-agent-tooling`, a repo-local flake app/package that installs
  shared AGENTS files, repo-managed skills, agent CLI wrappers, and
  `ghostship-agent-maintenance` into a user home so a fresh Codex image can be
  rehydrated without rebuilding the image.

## [2.1.67] - 2026-06-08

- **Codex external agent tooling bootstrap**: Keep `agent-browser` in the Codex
  container image, but move mutable agent CLI and skill maintenance outside the
  image. Host startup now copies the maintenance script, shared AGENTS files,
  and repo-managed skills into persisted `/home/codex`; container setup runs
  that external script so Codex, Gemini, OpenCode, skills, and browser runtime
  updates do not require rebuilding the image.

## [2.1.66] - 2026-06-08

- **Codex agent tooling bootstrap**: Include shared agent maintenance tooling in
  the Codex container image, target it at `/home/codex`, and run it during
  container setup so rebuilt images refresh Codex, Gemini, OpenCode, skills,
  and `agent-browser` tooling inside the hosted Codex environment. Container
  setup also relinks the repo-managed shared AGENTS file and skills into
  `/home/codex` so persisted homes cannot keep stale skill symlinks from older
  images.

## [2.1.65] - 2026-06-08

- **Codex web refresh**: Update the Codex container to the latest
  `0xcaff/codex-web` flake input.

## [2.1.64] - 2026-06-07

- **Codex container Git LFS**: Add `git-lfs` to the Codex container image so
  hosted Codex sessions can fetch and work with LFS-backed repositories.

## [2.1.63] - 2026-06-07

- **Codex image-owned Nix store**: Stop bind-mounting and reseeding `/nix` for
  the Codex container. The image now owns `/nix`, and startup clears the Codex
  user's mutable Nix DB/profile/cache state when the image generation changes
  so user metadata cannot point at paths from the previous image.

## [2.1.62] - 2026-06-06

- **Muximux Grimmory bundle rewrite**: Rewrite Grimmory's current
  `text/javascript` bundles and runtime base-url API calls through the
  `/grimmory/` proxy so the UI calls the proxied API path.

## [2.1.61] - 2026-06-05

- **Codex Nix seed validation**: Reseed the persisted Codex container `/nix`
  tree when required wrapper or Node runtime paths are missing, even if the
  image marker already matches.

## [2.1.60] - 2026-06-05

- **Codex Nix store seeding**: Replace the persisted Codex container `/nix`
  tree when the image changes so new image store paths and symlink targets are
  not lost during deployment.

## [2.1.59] - 2026-06-05

- **Codex share mount**: Make `podman-codex` wait for the host
  `/mnt/share` NFS mount before starting so the container's `/mnt/share`
  bind mount sees the live library share.
- **WSL share mount path**: Move develop-host Synology NFS automounts from
  `/mnt/z` to `/mnt/share`, while clearing stale `/mnt/z` mount state during
  activation.

## [2.1.58] - 2026-06-04

- **Codex s6 service packaging**: Package Codex s6 service run scripts as
  image-compatible binaries so the container image builds cleanly.

## [2.1.57] - 2026-06-04

- **Codex container supervision**: Run the Codex container under s6, add
  `supercronic`, `webhook`, and `task`, and persist cron, webhook, and Taskfile
  automation under `/home/codex/.automation`.

## [2.1.56] - 2026-06-04

- **Prefect retirement**: Remove the Prefect workflow stack, its PostgreSQL and
  Redis support containers, and its Homepage and Muximux dashboard entries from
  `chill-penguin`.

## [2.1.55] - 2026-06-04

- **Developer SSH public key**: Manage `id_ed25519_dev.pub` through the
  develop-host Home Manager profile alongside the encrypted private key.

## [2.1.54] - 2026-06-04

- **Autoreview skill**: Vendor OpenClaw's MIT-licensed `autoreview` skill,
  tailor its instructions for Codex-only review closeout, and link it into
  develop-host shared skills.

## [2.1.53] - 2026-06-04

- **Developer SSH key secret**: Encrypt `id_ed25519_dev` as a develop-host
  home secret and keep Git plus `chill-penguin` SSH using that key.

## [2.1.52] - 2026-06-04

- **Chill Penguin SSH profile**: Replace the stale root-only host alias with
  the active `chill-penguin` SSH profile.

## [2.1.51] - 2026-06-04

- **Muximux Grimmory loading**: Route Grimmory through a same-origin
  `/grimmory/` Muximux proxy, align its health check with the documented
  `/api/v1/healthcheck` endpoint, and mount library/bookdrop paths at the
  container paths expected by current Grimmory images.

## [2.1.50] - 2026-06-04

- **NZBGet container startup**: Keep NZBGet behind Gluetun, seed the
  LinuxServer container auth env to match Homepage, and pin `ScriptDir` to the
  mounted scripts directory so newer NZBGet releases do not look under the app
  install path.
- **Homepage Prefect icon**: Replace the invalid selfh.st Prefect icon
  reference with the Simple Icons Prefect glyph.

## [2.1.47] - 2026-06-02

- **Muximux pyLoad API polling**: Proxy pyLoad's root `/json/` polling
  endpoints through Muximux so the same-origin dashboard can refresh status and
  queue data instead of logging 404s.

## [2.1.46] - 2026-06-02

- **Muximux proxy asset paths**: Proxy pyLoad's root `/web/` assets through
  Muximux, keep pyLoad's session cookie available to those asset requests, and
  fix RomM's root `/assets/` and `/api/` proxy paths so dynamically referenced
  assets do not fall back to Muximux.

## [2.1.45] - 2026-06-02

- **Muximux pyLoad redirects**: Force same-origin pyLoad proxy redirects to
  stay on HTTPS so Cloudflare-served Muximux iframes do not hit mixed-content
  redirects after pyLoad autologin.

## [2.1.44] - 2026-06-02

- **Muximux iframe fixes**: Route pyLoad through a same-origin `/pyload/`
  Muximux proxy with redirect and cookie-path rewrites, fix RomM's `/romm/`
  proxy prefix stripping so asset requests return JavaScript/CSS instead of the
  Muximux app shell, and remove the non-web SSH Access endpoint from Muximux.

## [2.1.43] - 2026-06-02

- **Muximux iframe audit tooling**: Add a repeatable `agent-browser` based
  audit script and documentation for testing Muximux entries through the real
  Cloudflare Access path before making iframe fixes.

## [2.1.42] - 2026-06-01

- **Prefect startup ordering**: Use unique generated env temp files and make
  Prefect services wait for Redis so concurrent service starts do not race.

## [2.1.41] - 2026-06-01

- **Prefect support image pulls**: Reuse cached PostgreSQL and Redis images on
  service restarts while keeping Podman registry auto-update labels, preventing
  Docker Hub rate limits from blocking Prefect support services.

## [2.1.40] - 2026-06-01

- **Prefect Redis cache**: Run Prefect Redis without snapshot persistence so
  background services keep accepting writes even when RDB saves would fail.

## [2.1.39] - 2026-06-01

- **Prefect image pulls**: Reuse cached Prefect images on service restarts
  while keeping Podman registry auto-update labels, avoiding Docker Hub rate
  limits during rebuilds.

## [2.1.38] - 2026-06-01

- **Prefect database bootstrap**: Ensure the Prefect PostgreSQL database exists
  before starting the server so reused state directories can migrate cleanly.

## [2.1.37] - 2026-06-01

- **Prefect workflow stack**: Replace Windmill with Prefect as the final
  workflow orchestrator design, restore the Prefect Podman stack, wire
  dashboards to `prefect.ghostship.io`, and retire Windmill artifacts.

## [2.1.36] - 2026-06-01

- **Muximux qBittorrent icon**: Use a distinct magnet icon for qBittorrent
  instead of sharing NZBGet's download icon.

## [2.1.35] - 2026-06-01

- **Muximux qBittorrent order**: Keep qBittorrent in the same Muximux position
  previously occupied by VueTorrent, directly after NZBGet.

## [2.1.34] - 2026-06-01

- **qBittorrent runtime identity**: Rename the managed torrent container,
  systemd units, dashboard entries, and Gluetun restart wiring from
  `vuetorrent` to `qbittorrent` while keeping the VueTorrent alternate WebUI
  installed as the qBittorrent UI.

## [2.1.33] - 2026-06-01

- **Windmill official-base image**: Restore Windmill and build the
  `JEMALLOC_SYS_WITH_LG_PAGE=14` binary as an overlay on top of the official
  Windmill image instead of using a fully custom Nix root filesystem.

## [2.1.32] - 2026-06-01

- **Hatchet workflow stack**: Replace the short-lived Prefect stack with a
  Hatchet control plane using PostgreSQL-backed messaging, wire Homepage and
  Muximux to `hatchet.ghostship.io`, and retire Prefect runtime artifacts.

## [2.1.31] - 2026-06-01

- **Prefect workflow stack**: Replace the Windmill stack with a Prefect 3
  Podman deployment backed by PostgreSQL and Redis, wire Homepage and Muximux
  to `prefect.ghostship.io`, and retire Windmill runtime artifacts.

## [2.1.30] - 2026-06-01

- **Windmill worker isolation**: Override the worker unshare flags to avoid
  Podman's denied `--mount-proc` path while keeping PID unshare enabled.

## [2.1.29] - 2026-06-01

- **Windmill worker startup**: Include `unshare` in the repo-built Windmill
  Podman image so the worker can satisfy `ENABLE_UNSHARE_PID` and stay running
  on `chill-penguin`.

## [2.1.28] - 2026-06-01

- **Windmill workflow stack**: Replace n8n with a repo-managed Windmill
  server, worker, and PostgreSQL Podman stack; rebuild the Windmill container
  with `JEMALLOC_SYS_WITH_LG_PAGE=14` for Apple Silicon page-size
  compatibility; wire dashboard entries to `windmill.ghostship.io`; and retire
  the now-unused SearXNG search/cache containers, secrets, dashboards, and
  runtime artifacts.

## [2.1.27] - 2026-06-01

- **Self-hosted service retirement**: Retire Changedetection and PriceBuddy
  now that n8n replaces the change-monitoring workflow and PriceBuddy appears
  abandoned. Remove their local image contexts, secret wiring, refresh timers,
  dashboard entries, containers, and stale runtime artifacts.

## [2.1.26] - 2026-06-01

- **Self-hosted service retirement**: Retire BentoPDF, ConvertX, IT Tools,
  MeTube, and OmniTools from the `chill-penguin` stack, add cleanup for their
  stale containers/images/dashboard entries, redistribute Homepage utilities,
  and replace the broken Codex Homepage icon.

## [2.1.25] - 2026-06-01

- **CloakBrowser extension refresh**: Keep the last known-good unpacked
  extension when an upstream extension download temporarily fails, while still
  failing if no usable installed copy exists.

## [2.1.24] - 2026-06-01

- **Container auto-update auth**: Extend the shared Podman registry auth file
  to cover `docker.n8n.io` as well as Docker Hub so n8n auto-update checks do
  not fall back to anonymous pulls and fail on registry rate limits.

## [2.1.23] - 2026-05-31

- **Local image refresh**: Add daily forced rebuild timers for the local
  Changedetection and PriceBuddy scraper CloakBrowser images so their `latest`
  base images update automatically before the running services restart. The
  refresh services also prune stale hash-tagged local image leftovers after the
  restarted service adopts the current tag, and automatic NixOS upgrades no
  longer try to commit lock-file changes from remote flake checkouts.

## [2.1.22] - 2026-05-31

- **Develop and secret cleanup**: Remove duplicate Home Manager OpenCode
  wrapper wiring, drop the unused CIFS package from develop hosts, and retire
  unused n8n, Electron Hub, Google AI Studio, NVIDIA Build, SMB, and Zenmux
  secret catalog entries.

## [2.1.21] - 2026-05-31

- **Retired image cleanup**: Add leftover upstream Agent Zero and local Honcho
  image repositories to the `chill-penguin` retired artifact cleanup inventory.

## [2.1.20] - 2026-05-31

- **Develop module cleanup**: Remove the unused `modules/develop/core.nix`
  duplicate now that develop hosts import `modules/develop/default.nix`.

## [2.1.19] - 2026-05-31

- **Codex mobile patch cleanup**: Remove temporary manifest, service worker,
  debug overlay, and route fallback changes while keeping the mobile viewport
  clamp that fixes Android thread input clipping.

## [2.1.18] - 2026-05-31

- **Codex mobile shell height**: Clamp the hydrated Codex app shell and main
  content viewport to the measured mobile visual viewport so first-load thread
  pages do not extend under Android Chrome controls.

## [2.1.17] - 2026-05-30

- **Codex hydration diagnostics**: Keep the mobile debug overlay refreshing
  after React root mutations so thread screenshots capture hydrated app state
  instead of only the startup loader.

## [2.1.16] - 2026-05-30

- **Codex deep-link diagnostics**: Keep mobile helper assets root-relative on
  thread routes, avoid serving the SPA shell for asset-like 404s, and report
  client runtime errors in the mobile debug overlay.

## [2.1.15] - 2026-05-30

- **Codex mobile diagnostics**: Add a temporary `?ghostship-debug=1` overlay
  that reports Android viewport, composer positioning, service worker, and
  install-prompt state from the device.

## [2.1.14] - 2026-05-30

- **Codex Android clearance**: Give the mobile floating composer a fixed
  Android navigation clearance fallback and keep the manifest link unversioned
  while no-store headers handle freshness.

## [2.1.13] - 2026-05-30

- **Codex mobile viewport owner**: Apply the mobile bottom inset to Codex's
  main content viewport, use the small viewport height on touch devices for
  first paint, and serve the PWA manifest with the manifest media type.

## [2.1.12] - 2026-05-30

- **Codex mobile first-load inset**: Re-run the visual viewport sizing after
  DOM readiness, page load, animation frames, and short Android browser-chrome
  settle delays so the follow-up composer clears mobile controls before focus.

## [2.1.11] - 2026-05-30

- **Codex mobile installability**: Add a real service worker, 192px PWA icon,
  and body-level mobile bottom inset so Chrome can install the app and the
  portal-mounted follow-up composer clears mobile browser controls.

## [2.1.10] - 2026-05-30

- **Codex patched launcher**: Repoint the copied `codex-web` launcher at the
  patched package output so the live server uses the mobile and manifest fixes.

## [2.1.9] - 2026-05-30

- **Codex static cache disable**: Disable Fastify Static's default cache
  header on the Codex webview root and apply no-store headers there directly.

## [2.1.8] - 2026-05-30

- **Codex static shell headers**: Set no-store headers from Fastify Static's
  file header hook so the app shell and manifest are not overwritten by static
  defaults.

## [2.1.7] - 2026-05-30

- **Codex shell cache enforcement**: Disable Fastify's default static cache
  header for the Codex webview root so the app-shell no-store hook is not
  overwritten.

## [2.1.6] - 2026-05-30

- **Codex shell cache control**: Mark Codex HTML, manifest, mobile viewport
  script, and SPA fallback responses as non-cacheable so authenticated browser
  paths stop reusing stale app-shell metadata.

## [2.1.5] - 2026-05-30

- **Codex mobile inset priority**: Mark the mobile composer bottom inset
  override important so later upstream bundle CSS cannot reset it.

## [2.1.4] - 2026-05-30

- **Codex mobile cache bust**: Inline the mobile viewport override into the
  Codex web HTML and version the manifest link so mobile browsers do not keep
  stale hashed assets or manifest metadata.

## [2.1.3] - 2026-05-30

- **Codex installable web app**: Add standalone PWA manifest metadata and iOS
  standalone web-app tags to the patched Codex web bundle.

## [2.1.2] - 2026-05-30

- **Codex mobile viewport**: Patch the Codex web bundle in the container image
  to use the mobile visual viewport and safe bottom inset so the floating
  composer is not clipped behind mobile browser chrome.
- **Codex Ollama proxy fix**: Strip the UI-only `ollama/` model prefix from
  Ollama-compatible JSON request bodies before forwarding them to ollama.com.

## [2.1.0] - 2026-05-30

- **Codex Ollama picker**: Add Ollama to the Codex web container, run Codex web
  and an authenticated ollama.com API proxy as the persistent `codex` user,
  project the Ollama API key into the container, and route the live
  ollama.com model list filtered to `tools`, `thinking`, and `cloud` models
  through Codex CLI's native Ollama provider while keeping GPT models in the
  same picker.
- **Codex Bitwarden CLI**: Add Bitwarden CLI to the Codex web container and
  project `BW_CLIENTID`, `BW_CLIENTSECRET`, and `BW_PASSWORD` into the Codex
  runtime environment.
- **Muximux clipboard permission**: Allow clipboard read/write in service
  iframes so Codex copy actions work when opened through `apps.ghostship.io`.

## [2.0.24] - 2026-05-30

- **Codex Nix seed tracking**: Track the built Codex image store path when
  seeding the persistent `/nix` mount so package changes reseed runtime store
  artifacts even when the upstream image tag is unchanged.

## [2.0.23] - 2026-05-30

- **Codex container GitHub CLI**: Add GitHub CLI to the Codex web container
  alongside Git so hosted Codex sessions can run `gh` workflows.

## [2.0.22] - 2026-05-30

- **BookStack removal**: Remove BookStack and its MariaDB sidecar from the
  `chill-penguin` self-hosted stack, including secret projections, dashboard
  entries, modules, and retired live container/config artifacts.

## [2.0.21] - 2026-05-30

- **Codex web service**: Restore Codex as a repo-built Podman OCI service for
  `codex.ghostship.io` using `0xcaff/codex-web`, the Codex CLI, Nix, Git, SSH,
  Docker-in-Docker, Python, Node.js, `uv`, `direnv`, search tools, and basic
  build tools, with persistent `/nix`, `/workspace`, `/home/codex`, Docker
  state seeded from the built image's Nix store, and `/mnt/share` mounted into
  the container.

## [2.0.20] - 2026-05-30

- **JDownloader2 removal**: Remove the headless JDownloader2 service, secret
  projection, dashboard entries, and retired live container/config/image
  artifacts from the `chill-penguin` self-hosted stack.

## [2.0.19] - 2026-05-29

- **JDownloader2 self-hosted service**: Add a headless
  `jlesage/jdownloader-2:latest` container on `chill-penguin` with
  MyJDownloader credentials projected from the new `jdownloader` secret,
  downloads rooted at `/mnt/share/Downloads/JDownloader2`, and
  Homepage/Muximux links to `https://my.jdownloader.org/`.

## [2.0.18] - 2026-05-28

- **Self-hosted agent containers**: Retire the Codex and Agent Zero
  `chill-penguin` containers, dashboard entries, secrets projections, and
  persistent Podman artifacts.
- **CloakBrowser extension defaults**: Make uBlock Origin Lite default to
  complete filtering instead of optimal, and make Bypass Paywalls Clean enable
  all regular default sites when extension storage is empty.
- **CloakBrowser reset**: Remove the CloakBrowser profile-default patching path
  so the manager UI and API keep upstream profile defaults while retaining the
  extension launch fix.
- **CloakBrowser extension defaults**: Persist requested uBlock Origin Lite and
  Bypass Paywalls Clean first-run defaults in the managed extension refresh,
  including complete uBOL filtering, selected rulesets, BPC custom sites, update
  checks, set-cookie opt-in, and suppressed update option pages.
- **CloakBrowser extension launch fix**: Allow Playwright-managed
  CloakBrowser profiles to load unpacked extensions by ignoring the default
  `--disable-extensions` Chromium flag, and disable auto-launch in the
  recommended profile payload.
- **CloakBrowser extensions**: Add a daily extension refresh service that
  unpacks and configures uBlock Origin Lite, I still don't care about cookies,
  and Bypass Paywalls Clean under CloakBrowser data, remove startup creation of
  a managed default profile, and document the recommended API profile payload.

## [2.0.10] - 2026-05-28

- **CloakBrowser manager restore**: Reintroduce the standalone
  `cloakhq/cloakbrowser-manager` service on `chill-penguin` with internal
  `ghostship_net` networking only, restore Homepage and Muximux entries, and
  stop retired-artifact cleanup from deleting its state.

## [2.0.9] - 2026-05-27

- **Shared skill curation**: Vendor Matt Pocock's MIT-licensed `grill-me`
  skill into the repo-managed shared skill set, remove the managed global
  `brainstorming` install, and clean stale `brainstorming` skill state during
  develop-host activation.

## [2.0.8] - 2026-05-26

- **Codex provider wiring**: Remove the standalone `/workspace` mount so Codex
  uses its persisted home as the working area, and seed a managed local provider
  mux for Ollama Cloud and OpenCode Go credentials.

## [2.0.7] - 2026-05-26

- **Codex web service**: Add a Nix-based `codex` Podman service for
  `codex.ghostship.io` with Docker-in-Docker support, persistent Codex home,
  workspace, nested Docker state, and `/nix` storage, plus a dedicated refresh
  timer and Homepage/Muximux entries.

## [2.0.6] - 2026-05-25

- **Agent Zero DinD contract**: Run the Agent Zero container privileged so the
  latest image can start its nested Docker daemon and manage bridge networking.

## [2.0.5] - 2026-05-23

- **Agent Zero Muximux icon**: Switch the Agent Zero Muximux tile to the
  triangular `muximux-archlinux` glyph so it visually tracks the Homepage
  Agent Zero A mark more closely.

## [2.0.4] - 2026-05-22

- **Agent Zero Muximux icon**: Replace the Homepage-style home glyph with the
  Muximux-native `muximux-brand-dot-ai` icon for a closer AI/A-style mark.

## [2.0.3] - 2026-05-22

- **Agent Zero Muximux icon**: Switch the Agent Zero Muximux tile to the
  existing Homepage-style `muximux-home2` icon.

## [2.0.2] - 2026-05-22

- **Agent Zero dashboards**: Add Agent Zero to Homepage's Management group
  directly after Muximux and to Muximux directly after Grimmory, using the
  public `https://agent-zero.ghostship.io` route.
- **Retired image cleanup**: Expand `chill-penguin` retired artifact cleanup
  to prune remaining Hermes and Firecrawl image repositories, and add the
  Homepage NZBGet widget auth fields while keeping the internal URL on
  `http://gluetun:5001`.
- **Develop login shell**: Set develop-role users to `fish` directly.
- **Codex Desktop WSL shell handling**: Keep the NixOS user shell on fish while
  letting Codex Desktop use the standard WSL shell path without the temporary
  fish-wrapper compatibility override.

## [2.0.1] - 2026-05-21

- **Ghostship audit worktree skill**: Rename
  `ghostship-review-worktree` to `ghostship-audit-worktree` across the
  repo-managed skill tree and develop-host skill link.
- **Ghostship audit worktree scope**: Refocus
  `ghostship-review-worktree` on current Codex session changes instead of
  pre-merge comparison against `main`, and remove changelog/version review
  duties from that skill.

## [2.0.0] - 2026-05-21

- **Hermes and Firecrawl retirement**: Remove the deprecated Hermes
  `ghostship-hermes` service and the full Firecrawl stack from
  `chill-penguin`, including their self-hosted modules, Firecrawl image build
  contexts, Firecrawl secret source, Hermes runtime projections, dashboard
  entries, and active README guidance.
- **chill-penguin retired artifact cleanup**: Add an allowlist-only self-hosted
  cleanup module for retired `chill-penguin` services. Activation now stops and
  removes known retired Hermes, Firecrawl, Honcho, LiteLLM, and standalone
  CloakBrowser manager units/containers, deletes their `/srv/apps` state, prunes
  retired project images, and removes stale Homepage/Muximux rows.
- **Retired agent tool cleanup**: Remove managed Paseo, Agent Deck, and the
  WSL OpenCode server service while keeping the OpenCode CLI, add exact cleanup
  for their retired user config/state paths plus browser-use and Caveman skill
  artifacts, and switch managed global skill refreshes to the installed
  `skills` CLI with `brainstorming` verified under shared `.agents`.

## [1.0.3] - 2026-05-21

- **NZBGet Gluetun routing**: Move NZBGet back into Gluetun's VPN namespace and
  update internal Homepage and Hermes URLs to `http://gluetun:5001`.

## [1.0.2] - 2026-05-21

- **VS Code WSL launcher fix**: Resolve the generated `/usr/bin/sh` wrapper
  path before locating its paired `shell`, so FHS shims that symlink to the
  wrapper still launch the real shell correctly.

## [1.0.1] - 2026-05-21

- **Shared PR workflow skill pruning**: Remove the repo-managed
  `github-pr-workflow` skill from develop host links, Codex skill config, and
  stale artifact cleanup.

## [1.0.0] - 2026-05-21

- **Shared skill pruning**: Remove deprecated repo-managed `codex-queue`,
  `nix`, `python`, `skill-creator`, `ssh`, and `wsl2` skills from develop host
  links, Codex skill config, and stale artifact cleanup.
- **Ghostship worktree review skill**: Add `ghostship-review-worktree` as the
  local worktree pre-merge review workflow for concrete issue finding and fix
  planning before merge, while keeping `ghostship-merge-worktree` as the local
  merge workflow used after approval.
- **Ghostship pull worktree skill**: Add `ghostship-pull-worktree` for the
  draft PR path from a worktree, including Codex review, CI follow-up, and
  ready-for-merge gating.
- **Ghostship merge worktree skill**: Replace the bundled merge helper tooling
  with an instruction-only direct merge workflow that updates `main`, handles
  drift and conflicts, verifies `main`, and pushes without using the PR path.
- **Ghostship review worktree checks**: Extend `ghostship-review-worktree` to
  review documentation, changelog, and semantic versioning consistency before
  merge.
- **Develop artifact cleanup inventory**: Add a single Home Manager cleanup
  module for retired develop-user artifacts, moving old Superpowers, managed
  Caveman, and Workmux cleanup into one maintained activation entry.
- **Codex Desktop WSL fish compatibility**: Override only the NixOS-WSL
  `shell-wrapper` on WSL hosts so nested Bash-quoted worktree probes bypass
  fish parsing after importing the normal NixOS and fish environment, while
  develop users still default to fish.
- **NZBGet networking**: Move NZBGet off Gluetun's VPN namespace and onto
  `ghostship_net`, updating the internal Homepage URL to `http://nzbget:5001`.
- **Podman auto-update auth**: Merge Agent Zero's GHCR auth into the shared
  Podman auto-update auth file so the daily registry update pass can check the
  private Agent Zero image without failing the whole run.
- **VueTorrent startup**: Stop fetching the VueTorrent LinuxServer Docker mod
  during qBittorrent container startup so the download stack can reach a
  healthy WebUI without depending on a GHCR mod fetch inside the VPN namespace,
  mount a pinned VueTorrent `v2.33.0` release from the Nix store, normalize the
  WebUI address line for the LinuxServer wrapper, and remove stale qBittorrent
  lockfiles before startup.
- **Agent Zero Nix persistence**: Mount `/nix` through a Podman named volume
  with copy-up so the Ghostship Agent Zero image keeps its baked-in Nix install
  while persisting runtime Nix state.
- **Agent Zero Google AI Studio key**: Project the shared Google AI Studio
  provider secret into Agent Zero as `GOOGLE_API_KEY`.
- **Agent Zero shared memory**: Increase the Agent Zero container shared memory
  mount to 2 GiB for browser-heavy workloads.
- **Worktree PR handoff**: Tighten shared agent policy so worktree work must
  end with a pushed branch, draft-first PR, reviewed Codex comments, checked CI,
  resolved conflicts, and a ready/non-WIP PR before user handoff when unblocked.
- **WSL FHS shim replacement**: Replaced patched `envfs` on WSL hosts with
  explicit writable `/bin/...` and `/usr/bin/...` shims under
  `ghostship.wsl.fhsShims`, preserving the known shell, Starship, Node, GitHub
  CLI, and NixOS-WSL helper paths while leaving Docker Desktop free to create
  `/usr/bin/docker-credential-desktop.exe` at runtime.
- **GitHub PR workflow skill**: Add a shared `github-pr-workflow` skill for
  draft-first PRs, native automatic Codex review defaults, review feedback
  handling, merge-conflict readiness, and shared GitHub Actions CI defaults,
  and retire the local `merge-worktree` skill from the shared skill set.
- **Agent Zero plugin contract**: Project the new Agent Zero plugin runtime
  environment names, including `BW_CLIENT_ID`, `BW_CLIENT_SECRET`, and the
  provider plugin API keys for Ollama Cloud, OpenCode Go, NVIDIA Build Free,
  OpenCode Zen Free, and OpenRouter Free.
- **Muximux Cloudflare recovery**: Point RomM at the live NAS ROM library under
  `/mnt/share/Library/ROMS/ROMS`, create its `.romm` assets directory before
  container start, and make the Muximux RomM proxy resolve `romm` at request
  time so a stopped RomM container no longer prevents the dashboard nginx from
  starting.
- **Agent Zero stack service**: Add Agent Zero as an internal-only self-hosted
  Podman service on `ghostship_net`, using the Ghostship GHCR image with
  Bitwarden CLI credentials projected from the shared Bitwarden source.
- **Source-based secret bundles**: Replaced service-tied ragenix bundles with
  source/provider/service files under `secrets/files/sources`, added shared
  runtime recipients for ScreenScraper and RetroAchievements, and moved services
  onto projected `/run/ghostship-secrets` env files while keeping runtime env
  names stable. Firecrawl now gets `OPENAI_API_KEY` from the Google AI Studio
  source, and `OPENCODE_ZEN_API_KEY` is projected from OpenCode Go's
  `GO_API_KEY` instead of stored separately.
- **Boomer emulator recovery hardening**: Generate Ryubing controller IDs from
  Linux input modalias bus/VID/PID/version fields and Ryubing's
  launch-environment input ID list when available, fail Switch smoke tests on
  Ryubing controller rejection logs, force Ryubing launched games to use the
  managed global input profile, mirror that input profile into per-title
  Ryubing configs, keep the standalone hotkey broker attached to the emulator
  process group, and expose verified USB controller pairing through Bluetooth
  Settings with a kiosk-visible message path.
- **PyLoad failed-download retry**: Add a daily `04:00`
  `pyload-restart-failed` systemd timer that runs a one-shot helper on
  `ghostship_net`, checks pyLoad's queue through `http://pyload:8000`, and
  calls the native `restart_failed` API when failed links are present.
- **Boomer controller recovery**: Treat wired Switch Pro-style controllers as
  USB in the resolved launch map, stop USB plug-in events from running the
  broken Bluetooth reconnect wrapper, make Reconnect All a bounded all-device
  pass, disable the always-running controller autoconnect and Bluetooth health
  diagnostics, and remove legacy hidden ES-DE menu tool scripts.
- **Boomer GameMode fix**: Add the kiosk user to the `gamemode` group and set
  conservative GameMode defaults so emulator launches can apply the
  performance governor, renice, I/O priority, and split-lock policy without
  `pkexec` authorization failures.
- **Boomer physical controller maps**: Make Switch Pro/8BitDo face buttons
  physical across emulator launch config, keep RetroArch hotkey gestures on the
  same physical buttons, set left analog as D-pad only for digital-only
  RetroArch systems, map N64 A/B to physical B/Y, align Dolphin GameCube face
  buttons physically, and add Dreamcast `.elf/.lst/.dat` ES-DE launch coverage.
- **Boomer USB controller reconnect fix**: Count wired resolved controllers in
  Bluetooth Settings status, run the legacy Reconnect Controllers tool through
  the bounded 10-second connector, and keep USB-assisted pairing bounded
  without enabling `joycond` by default.
- **Boomer RetroArch launch fix**: Own the resolved controller runtime
  directory as the kiosk user so launch-time RetroArch player-order append
  configs can be written before the emulator starts.
- **Boomer resolved controller launches**: Add a pre-launch controller resolver
  that reconciles LEDs, writes connected-only player order under `/run`, and
  feeds RetroArch, Dolphin, PCSX2, Ryubing, and Xemu launch-time input config.
- **Boomer stable emulator audio**: Prefer PipeWire SDL3 audio with 48 kHz/1024
  frame stable buffering, add matching PipeWire/Pulse defaults, and set Xemu
  audio to `use_dsp = false` and `hrtf = false`.
- **Boomer ES-DE collections**: Seed empty Local Multiplayer and Co-op custom
  collections and enable them in ES-DE settings for later manual population.
- **Boomer PS2 m3u and multiplayer support**: Resolve PS2 `.m3u` playlists in
  `run-emulator` before launching PCSX2, seed a Soulcalibur III playlist when
  the CHD exists, enable PCSX2 port 1 multitap with four SDL controller slots,
  turn on MTVU with neutral cycle settings, and add token-backed PCSX2
  RetroAchievements projection.
- **Boomer PS2 PCSX2 setup**: Manage standalone PCSX2 `2.6.3` before each PS2
  launch with no setup wizard, Vulkan 3x graphics, managed BIOS/ROM/data
  paths, direct `-batch -fullscreen` launches, SDL controller mappings, and
  native PCSX2 hotkey chords for pause menu, reset, save/load slot 1,
  screenshot, OSD/FPS, and hold-turbo.
- **Boomer Switch Ryubing setup**: Manage Ryubing's current lower-case config
  schema before Switch launches, install the newest local firmware archive into
  Ryubing's native `registered/<nca>.nca/00` firmware store layout, keep the
  Canary pin current, and add hidden `.updates`/`.dlc` auto-registration for
  Ryubing title updates and DLC, including native `/...nca` DLC PFS paths.
  Add Switch hotkeys for Minus + X -> F4, Minus + A -> F8, and Square/Capture
  -> F5 through targeted Ryubing X window key events while preserving Minus +
  Plus twice exit. Generate
  Ryubing SDL3 Pro Controller profiles with Ryubing-native stable SDL3 IDs for
  up to four connected players and tune Switch launches for the RX 6650M dGPU,
  2x internal resolution, 16x anisotropic filtering, Vulkan, docked fullscreen,
  shader/PTC cache, and non-null disabled LED config required by Ryubing's
  SDL3 controller backend. Keep ES-DE folders sorted first while hiding Switch
  `.updates` and `.dlc` staging folders.
- **Boomer Dolphin prompt fix**: Reassert Dolphin analytics opt-out and
  stop-confirm settings immediately before each launch with valid INI syntax
  plus Dolphin `-C` overrides, so GameCube kiosk launches do not ask to report
  usage data or confirm quit/stop.
- **Boomer GameCube Dolphin hotkeys**: Configure Dolphin to launch GameCube
  games without analytics, panic, or stop-confirm prompts, use the raw hotkey
  broker for reset, save/load slot 1, screenshot, and fast mode, and keep
  unsupported quick-actions/debug-monitor and bare Square chords explicitly
  unbound. Keep Dolphin's generated keyboard fallback hotkeys under the native
  `[Hotkeys]` section on Dolphin's `XInput2/0/Virtual core pointer` device and
  Dolphin's grouped hotkey keys such as `General/Reset`, then inject them
  through the same raw `ydotool` path used by other standalone hotkey profiles
  so Dolphin 2603 loads and receives them.
- **Boomer Dolphin native button map**: Correct Dolphin's generated SDL
  bindings so GameCube uses label aliases with A/B and X/Y swapped for
  Boomer's Switch Pro controller, Plus as Start, L1/R1 shoulder labels, and R2
  as the right trigger.
- **Boomer Controller Maps hotkey layout**: Render the same full hotkey combo
  list on every controller map with combo-first rows and `None` for unmapped
  actions. Use `L1`/`R1` for shoulder rows, `L2`/`R2` for trigger rows, keep
  stick clicks on `L3`/`R3`, and label hotkeys with spaced `Minus + ...`
  chords starting with `Minus + Plus 2x`.
- **Boomer hotkey and RetroAchievements regression fix**: Restore the
  per-launch Select+Start double-press exit broker, keep RetroArch hotkeys in
  the managed base config plus controller autoconfigs, add 8BitDo udev
  autoconfig aliases, and load generated RetroAchievements credentials as an
  explicit append config so RetroArch sync no longer strips them. Make
  `xemu-hotkeys` the default Xbox launcher so Xbox hotkeys work without
  selecting an alternate emulator.
- **Boomer PICO-8 hotkey launcher**: Make `pico8-hotkeys` the default, keep
  plain PICO-8 as the fallback alternate, launch PICO-8 with a managed
  `-home` directory, seed its config/controller mapping before launch, and map
  supported PICO-8 keyboard shortcuts through the standalone hotkey broker.
- **Boomer N64 Mupen64Plus-Next tuning**: Keep N64 on RetroArch
  Mupen64Plus-Next, switch the managed core options to GLideN64 with 3x native
  resolution, keep shaders on the global `global.slangp` preset, default all
  four N64 controller paks to rumble, and stop generating ParaLLEl N64 and
  shader-profile runtime option files.
- **Boomer standalone hotkey broker**: Replaced the old controller hotkey
  watcher with a generic broker. The shared per-launch broker handles
  Select+Start twice exit, while expanded standalone profiles stay opt-in. Xbox
  keeps plain `xemu` as the default and adds selectable `xemu-hotkeys` for Xemu
  save/load, reset, screenshot, pause, debug-monitor, and quick-action chords
  through a per-launch HMP socket plus host key injection.
- **Boomer controller mapping standardization**: Keep RetroArch on the managed
  base config, XDG `global.slangp`, and XDG per-core `.opt` files, force PC
  Engine-family cores to 6-button pads for all five players, and enable all
  four generated Dolphin GameCube controller ports while leaving analog-capable
  systems on analog stick input.
- **Boomer PC Engine CD launch fix**: Launch PC Engine CD games with Beetle PCE
  Fast, keep SuperGrafx for HuCard/SuperGrafx games, and sync libretro core
  info from `libretro-core-info` so RetroArch sees the managed metadata.
- **Boomer RetroArch core options**: Write managed core options to RetroArch's
  native XDG per-core layout so each core loads its defaults directly.
- **Boomer RetroAchievements defaults**: Enable RetroAchievements by default
  for RetroArch cores when credentials are present, with visible notifications,
  encore/start-active behavior, badges, rich presence, unlock screenshots, and
  unlock sounds while keeping hardcore mode off.
- **Boomer Beetle SuperGrafx config**: Manage the core's CD BIOS/cache settings,
  enable six-button joypads for all five controller ports, and keep multitap
  enabled.
- **Develop agent maintenance fix**: Fixed a failure in `ghostship-agent-maintenance` where a stale patch for `agent-deck` caused the script to exit before updating `gemini`, `codex`, and `opencode`. Removed the stale web-mutations patch for `agent-deck` (now upstreamed in `v1.7.75`) and made the build process non-fatal so it no longer blocks other agent updates.
- **Boomer Controller Maps hotkey audit**: Show emulator hotkeys only where
  they are actually configured, keeping RetroArch save-state controls off
  standalone emulator maps.
- **Boomer PICO-8 ES-DE support**: Seed a small starter set of existing NAS
  PICO-8 carts into an empty ES-DE ROM folder and document the PICO-8 Switch
  controller map in the on-device Controller Maps TUI and generated policy.
  Use clean `.png` PICO-8 cart names for ES-DE scanning.
- **Boomer ES-DE gamelists**: Stop generating ES-DE gamelists from Nix; let
  ES-DE own gamelist creation and updates.
- **Boomer TeknoParrot launchers**: Use TeknoParrot `.xml` profile files in
  ES-DE and launch them through `TeknoParrotUi.exe --profile` under Wine.
- **Boomer TeknoParrot Wine Mono**: Package the Wine Mono MSI expected by the
  managed Wine build and install it into TeknoParrot's Wine prefix before
  starting TeknoParrotUi.
- **Boomer TeknoParrot first-run setup**: Seed TeknoParrot's `ParrotData.xml`
  for kiosk launches and map friendly ES-DE XML profile names to the official
  TeknoParrot `GameProfiles` id before invoking `--profile`.
- **Boomer TeknoParrot ES-DE identity**: Show TeknoParrot as its own ES-DE
  system instead of reusing the generic Arcade theme label.
- **Boomer TeknoParrot theme**: Add TeknoParrot metadata, logo, and system
  artwork to the managed Art Book Next ES-DE theme so it does not render blank.
- **Boomer TeknoParrot polish**: Force ES-DE's custom systems order and copy
  selected XML profiles into TeknoParrot's `UserProfiles` directory before
  launching them.
- **Boomer TeknoParrot artwork**: Apply Art Book Next's diagonal system-art
  mask to the TeknoParrot After Burner artwork so it matches stock system
  panels, and remove the temporary Model 3/Supermodel theme artwork.
- **Boomer Model 3 library**: Add `Arcade - Model 3 (1996)` to ES-DE as a
  Supermodel-backed arcade library using the stock `model3` theme slot.
- **Boomer Supermodel setup**: Seed Supermodel's bundled `Games.xml` and
  `Music.xml` into the managed XDG config and its `Assets` into XDG data so
  Model 3 ROM sets and crosshair textures are detected.
- **Boomer Model 3 launch fix**: Launch Supermodel with force feedback enabled
  so Star Wars Trilogy Arcade clears its feedback-lever setup check.
- **Boomer Star Wars Trilogy setup**: Remove the optional Star Wars Trilogy
  drive-board ROM region from the managed Supermodel `Games.xml` so the game
  does not stop at the feedback-lever setup screen.
- **Boomer TeknoParrot logo**: Use the supplied path-based TeknoParrot SVG for
  the ES-DE system text logo.
- **Boomer controller probe documentation**: Document the live Switch Pro
  kernel event mapping from the Boomer raw input probe so emulator bindings can
  be based on observed `EV_KEY`/`EV_ABS` codes instead of inferred labels.
- **Boomer Xemu first-run setup**: Launch Xemu with the Nix-generated
  `xemu.toml` machine settings and disable Xemu's welcome wizard so Xbox games
  do not stop at the manual machine configuration prompt when the required BIOS
  and HDD files are present. Hide Xemu's menubar during gameplay, and have
  Xbox launchable images use the `.xiso` naming convention while redump
  backups stay outside ES-DE's `.iso` scan suffix.
- **Boomer emulation setup rendering**: Keep the generated GZDoom config
  Python heredoc flush-left so `emulation-setup.service` can complete during
  deployment.
- **Boomer GZDoom controller reset**: Restore the first Boomer GZDoom controls
  cfg from `e0e6880`, using named `Pad_*` controller aliases and no broad
  button unbind block. Reset stale `Doom.Bindings` and automap sections so
  GZDoom regenerates its generic defaults, while keeping the managed right-stick
  axis map and 25% vertical look scale.
- **Boomer GZDoom controller correction pass**: Apply the current in-game
  8BitDo Ultimate 2C probe as targeted `Joy*`/`POV1*` overrides: Y reloads
  instead of jumping, R1/L1 become User 2/User 1, L2 becomes alt-fire, Minus
  toggles automap, D-pad left/right change weapons, and D-pad up/down handle
  inventory.
- **Boomer GZDoom controller correction pass 2**: Keep the confirmed A/B/X,
  Minus, and D-pad mappings, move L1's remaining weapon-switch event from
  `Joy6` to User 1, add config-only R2 fire candidates for `Joy9` plus
  trigger-axis directions, and guess `Joy11`/`Joy12` for Plus/menu while
  leaving L4/R4 documented but unmapped until unique events are proven.
- **Boomer smoke-test kiosk restore**: Restore `greetd` instead of
  `getty@tty1` after root-run smoke tests on kiosk-mode hosts so Boomer returns
  to ES-DE instead of a console login prompt.
- **Boomer Switch Pro controller alignment**: Align generated controller maps
  and emulator policy around physical Switch Pro labels: Star/Home stays
  controller-local turbo, Select/Minus is the hotkey modifier, Select+X opens
  emulator quick menus where supported, Square/Capture opens native console
  Home only where explicitly configured, and unsupported Square/Capture actions
  are no-op.
  Seed GZDoom's SDL
  `[Joy:JS:*]` axis map so the right stick uses yaw/pitch instead of the Linux
  defaults that can look at the ceiling or treat vertical stick motion as
  left/right turning, with reduced vertical look sensitivity.
- **WSL OpenCode server port**: Move the WSL `opencode-server` Home Manager
  user service to `127.0.0.1:4096` for Windows desktop attachment.
- **VueTorrent download paths**: Persist qBittorrent's default save path at
  `/downloads/Torrent`, keep incomplete torrent data under
  `/downloads/Torrent/.incomplete`, and create that directory before
  VueTorrent starts so partfiles do not land in the shared downloads root.
- **Hermes shutdown signal**: Switch the `chill-penguin` Hermes container stop
  signal to `SIGTERM` so s6-overlay handles host-driven shutdown cleanly.
- **Codex queue skill**: Added a shared `codex-queue` skill for long
  manual-review Codex CLI queues with JSONL sharding, tmux-backed worktrees,
  idle-worker monitoring, ledger validation, smoke testing, and merge-preflight
  support while preserving the rule that final item judgments stay manual.
- **Boomer ES-DE tools menu**: Replace the individual controller and Wi-Fi
  tools with large-font `Bluetooth Settings` and `Wi-Fi Settings` TUIs that
  support keyboard and controller input, Bluetooth pairing/audio routing,
  player assignment, Wi-Fi profile management, and the 2.4 GHz policy toggle
  while keeping lower-level helper scripts available outside the visible menu.
  Launch the TUIs through Xwayland `xterm` in the ES-DE Gamescope session and
  log launcher diagnostics under `/srv/emulation/logs/tools/`. Refine the
  settings TUIs to a dark two-column layout with scroll-safe action lists,
  right-pane hover status, a single Bluetooth toggle, and hidden BlueZ host
  discoverable/pairable fields while retaining the active scanning state. Limit
  the raw input-event reader to controller-like devices so keyboard arrow
  presses are not handled twice, keep status blocks on the Status action only,
  compact Bluetooth status for four controllers plus headphones, and allow
  keyboard player assignment with B/Esc cancel. Fix Bluetooth pairing scans to
  run a real 10-second BlueZ discovery and parse newly discovered devices from
  the live scan output, filter the pairing picker to unconnected controllers,
  audio devices, and Bluetooth peripherals, and show whether each candidate is
  already paired. Register the BlueZ pairing agent during the pair command
  itself, tolerate BlueZ pair/connect commands that report an error after the
  device has already paired or connected, add a `Show Paired` Bluetooth menu
  item, ignore Switch Pro IMU/analog-stick idle noise in the raw input reader,
  and update controller LEDs through the controller-specific sysfs LED
  directory with Switch-style player counts. Add a controller-only Switch Pro
  autoconnect service, a `Controller Maps` TUI, and route `Restart ES-DE`
  through a dedicated delayed system service so it does not kill its own
  frontend session before the restart is queued. Tune Boomer's MediaTek
  MT7921/MT7961 Bluetooth stack for four Switch Pro controllers by preferring
  BR/EDR mode, disabling Wi-Fi power save and MT7921e ASPM, keeping BlueZ and
  `hid-nintendo` detailed debug logging available on demand instead of during
  normal play, removing joycond/cemuhook from the active service set,
  rate-limiting controller autoconnect, re-checking live connected state before
  each host-initiated connect, minimizing
  sysfs LED writes, and logging controller HID health plus pairing diagnostics.
  Dynamically compact connected controller player slots so remaining controllers
  slide down when a middle player disconnects and the returning controller joins
  at the end. Trigger controller slot reconciliation from controller input add
  events and BlueZ connected-property changes with short delayed retries for
  HID LED readiness, merge USB Switch-Pro HID nodes so USB controllers share the
  same player assignment and LED path, track the 8BitDo `2dc8:301a` wired USB
  mode as an input-only player identity, avoid treating stale Bluetooth HID
  nodes as connected when BlueZ no longer reports them, and serialize LED/order
  writes to reduce transient wrong player LEDs. Keep one-shot LED applies from
  being start-limited during fast reconnect cycles. Coalesce
  BlueZ-triggered retries through the one-shot unit and avoid force-writing
  already-correct LED entries so hid-nintendo output reports are not flooded.
  Debounce BlueZ event bursts and update the background state marker from
  one-shot applies to prevent immediate duplicate LED rewrites. Restore
  Boomer's default boot path to the ES-DE kiosk session, make the ES-DE restart
  tool handle both greetd kiosk mode and console mode, and give `bluetoothd`
  plus system D-Bus conservative CPU scheduling weight boosts without enabling
  realtime scheduling or IRQ pinning. Disable Bluetooth `SNIFF` low-power link
  policy for connected Switch Pro controllers so multiplayer sessions favor
  input latency over controller battery life. Make controller reconciliation
  fail-soft when BlueZ D-Bus is slow, rate-limit Switch LED sysfs writes to a
  half-second cadence, and modestly boost system D-Bus scheduling for BlueZ
  control traffic. Bound startup `btmgmt` tuning calls so a busy Bluetooth
  adapter does not hold controller services for long. Add Switch-style hotkeys
  with Select+X as quick menu,
  Select/Minus as the hotkey modifier, Star/Home documented as the controller
  turbo button, a raw controller hotkey monitor for normal emulator exits,
  left-stick-as-D-pad overrides for D-pad-only RetroArch systems, text-only
  two-column Controller Maps for every Boomer system family, an N64 direct A/B
  remap, and managed GZDoom Switch-style controller bindings plus a patched
  GZDoom menu confirm/back mapping.
- **Boomer Dolphin defaults**: Seed Dolphin analytics opt-out, fullscreen
  Vulkan graphics, audio, and Switch Pro controller defaults so GameCube, Wii,
  and WiiWare launches do not block on first-run dialogs.
- **Boomer WiiWare ROM support**: Add `.wad` and `.WAD` to the managed Wii
  ES-DE extensions so extracted WiiWare titles launch through Dolphin.
- **Boomer ES-DE preferences**: Enforce ES-DE's manufacturer/type/year
  systems sorting, display clock, Switch Pro controller prompts, and
  all-controller menu input during frontend config sync. Set Boomer to Hawaii
  standard time and patch Art Book Next's clock format with ES-DE-supported
  hour/minute tokens so the clock renders the hour.
- **Boomer service log cleanup**: Disable BlueZ's unused CSIP plugin alongside
  BAP, keep `audio-route` pointed at PipeWire Pulse instead of autospawning
  PulseAudio, and start UPower under the kiosk boot target for WirePlumber.
- **PyLoad download directory**: Set PyLoad's app config default download
  folder to `/downloads/PyLoad` during container initialization while keeping
  the shared `/downloads` mount unchanged, and remove the image's
  `--storagedir /downloads` command-line override so PyLoad honors the managed
  app setting.
- **Self-hosted secrets**: Limit the self-hosted secret module to
  `self-hosted-runtime` units so host-specific emulation secrets stay managed
  by the emulation module.
- **Boomer FBNeo and Switch launch fixes**: Fixed the performance harness so
  FBNeo's harmless romset search misses no longer classify a successfully loaded
  game as `blocked-missing-runtime`, documented the OutRun shader fallback path,
  and made Ryubing `.nro` launches expose sibling homebrew `data/` assets plus
  existing Switch keys through Ryubing's runtime directories.

- **Boomer Kuwanger emulation PC**: Added a dedicated `modules/emulation`
  NixOS module, enabled it on `boomer-kuwanger`, and wired ES-DE with Art Book
  Next, RetroArch cores, bundled shader packs including Mega Bezel, Gamescope
  FSR launch wrappers, standalone emulator coverage, PICO-8 `requireFile`,
  TeknoParrot free prefix scaffolding, Bluetooth/controller services, Wi-Fi
  disable policy, ES-DE tools, and scraper secret catalog entries. Split the
  module into focused submodules and added ROM disk options, per-core RetroArch
  option/override generation, display matrix testing, richer ES-DE tool menus,
  controller-order persistence, shader fallback status, ROM coverage checks,
  and standalone emulator config scaffolds. Declared Boomer's final label-based
  disk layout with the OS disk mounted at `/` and the ROM disk mounted at
  `/srv/emulation/roms`. Enabled durable SSH with root key login only, disabled
  password and keyboard-interactive SSH authentication, and added Boomer's host
  SSH key to the emulation secret recipient group. Replaced the first-pass
  Wi-Fi rfkill service with a 5 GHz-only NetworkManager profile policy so Wi-Fi
  remains available while avoiding 2.4 GHz associations for Bluetooth. Switched
  Boomer's bootstrap startup mode to a tty shell with `kiosk` auto-login and a
  manual `start-esde` Gamescope/ES-DE launch action until hardware
  bring-up is stable. Hardened Boomer's Wi-Fi bootstrap service so it waits for
  NetworkManager, clears stale Wi-Fi interface pins, and explicitly brings up
  saved 5 GHz profiles when autoconnect does not fire on first boot. Disabled
  BlueZ's unused BAP/CSIP LE Audio plugins on Boomer so the Bluetooth daemon
  stops logging ISO-socket errors while keeping controller-oriented Bluetooth
  active.
  Reworked the controller monitor to read BlueZ devices over D-Bus instead of
  polling `bluetoothctl`, added ES-DE preflight/status helpers, cleared
  unexpected service capabilities so the ES-DE AppImage can run under Gamescope,
  and verified manual ES-DE launch/stop with console recovery on the HX100G.
  Renamed public emulation tools and services to drop the project prefix, made
  Gamescope display selection dynamic across connected HDMI/DP outputs, narrowed
  ES-DE scraper secret wiring to ScreenScraper, and added smoke ROM selection,
  sync, launch-test, and report helpers. Added PipeWire HDMI audio routing that
  selects the currently available AMD HDMI/DP profile, exposed an ES-DE Audio
  Status tool, tightened smoke-test fatal-log detection, and documented that
  only proven failing smoke copies should be manually extracted. Added a
  one-page Boomer hardware/software/system overview document.
  Realigned Boomer's default emulator map with RetroAchievements-friendly
  choices, moved PC Engine to Beetle SuperGrafx, NES/FDS to FCEUmm, PS2 to
  standalone PCSX2, PSP to standalone PPSSPP, and 3DS to Azahar where
  available. Removed Gamescope FSR entirely, keeping Gamescope only as the
  fullscreen/session wrapper, changed the RetroArch default shader policy from
  Mega Bezel to clean NNEDI3/sharp profiles, kept Mega Bezel selectable, and
  added a dedicated RetroAchievements secret projection plus RetroArch runtime
  credential renderer. Added a repeatable emulator performance harness with
  quick, overnight, shader-matrix, scaling-matrix, report, compare, and profile
  tools that reuse `run-emulator`, parse MangoHud CSV frame metrics, and write
  tuning recommendations without automatically mutating runtime profiles.
  Cleared transient smoke/perf test capability sets so `steam-run`/bubblewrap
  emulators launch without the unexpected-capabilities failure seen during
  PICO-8 testing, and classified PICO-8 performance tests as 30 FPS by default
  because many carts, including the `POOM.png` smoke cart, target that rate.
  Replaced nixpkgs' stable Ryubing package with a pinned official Ryubing
  Canary binary package and added `update-ryubing-canary` so the pin can be
  advanced from the official latest redirect before Boomer rebuilds. Added
  Batocera-style `.gzdoom` launcher support for the Doom system so ES-DE can
  list curated launch files while GZDoom receives the referenced WAD/PK3 assets,
  and aligned Boomer's ES-DE ROM folder names exactly with the source
  `/mnt/z/Library/ROMs/roms` library.
  Added `POOM.png` as the PICO-8 smoke cart and made PICO-8 launches request
  an explicit Gamescope Xwayland server so SDL can initialize on the TV path.
  Forced ES-DE's live theme setting to Art Book Next during setup and changed
  frontend-launched games to reuse the existing ES-DE Gamescope session instead
  of starting a nested Gamescope compositor.

- **OpenSpec removal**: Removed the managed OpenSpec wrapper, generated agent
  command surfaces, repo-local planning tree, and stale CLI cleanup path from
  develop-host agent tooling. Removed the installed global
  `using-git-worktrees` skill in favor of the maintained `merge-worktree`
  workflow.

- **Hermes 36841a0 env contract**: Updated the `chill-penguin` Hermes env
  wiring for upstream `ghostship-hermes` `36841a0`, restoring
  `GHOSTSHIP_CODEX_CHANNEL=1492841053642817606`, adding
  `DISCORD_WEBHOOK_CHANNEL=1491229248856260799`, and adding staged
  `hermes-secrets` keys for OpenCode Zen, ZenMux, and Electron Hub router
  providers.

- **VueTorrent errored-torrent auto-resume**: Added a managed timer that
  retries errored qBittorrent torrents every 5 minutes without a per-torrent
  retry cap. The retry action uses qBittorrent 5's
  `/api/v2/torrents/start` endpoint.

- **VueTorrent queue limits**: Set the managed qBittorrent queue to 5 active
  downloads, 20 active torrents, a 20 MB/s global download limit, slow torrents
  excluded from active queue limits, and post-completion rechecks enabled.

- **Hermes latest-image contract update**: Updated the `chill-penguin` Hermes
  contract for upstream `ghostship-hermes` `main` at `8a1a5cb`: Codex primary
  is now `openai-codex/gpt-5.5`, the managed web backend is Firecrawl, and
  Hermes receives the image-owned Bitwarden CLI appdata path plus new
  `hermes-secrets` stubs for Bitwarden, GitHub, and NVIDIA Build credentials.

- **WSL patched envfs restore**: Restored `services.envfs` on WSL hosts for
  Linux/FHS paths such as `/usr/bin/bash`, kept Windows PATH import for desktop
  interop, patched envfs to ignore Windows/DrvFS PATH binaries under
  `/usr/bin` even when WSL exposes them as `9p` mounts with `aname=drvfs`, and
  allowed metadata/path probes so shebang launchers such as npm and npx can
  reopen envfs-synthesized entries without WSL wrappers.

- **Merge worktree finish contract**: Updated the shared `merge-worktree` skill
  so its bundled finish helper fast-forwards local `main` without removing the
  source worktree, and clarified that agents should invoke the helper from the
  installed skill path under `$HOME/.agents/skills/merge-worktree`.

- **Firecrawl CloakBrowser loader fix**: Switched the Firecrawl Playwright sidecar patch to load the ESM-only `cloakbrowser` package through a small CommonJS helper, so the embedded CloakBrowser path works under the upstream service's current Node/TypeScript build output.

- **Firecrawl Postgres arm64 fix**: Replaced the broken `ghcr.io/firecrawl/nuq-postgres:latest` sidecar on `chill-penguin` with a repo-owned multi-arch `nuq-postgres` build based on `postgres:16`, preserving Firecrawl's upstream `nuq.sql` and `pg_cron` initialization so the `nuq` schema comes up correctly on arm64.

- **Standalone CloakBrowser manager removal**: Retired the old `cloakhq/cloakbrowser-manager` service, removed its manager-era Changedetection keepalive unit and timer, dropped the Homepage and Muximux manager tiles, and left Changedetection, PriceBuddy scraper, Firecrawl Playwright, and Hermes on their embedded or image-owned CloakBrowser paths only.

- **Homepage group rebalance**: Rebalanced only Homepage's `Services`, `Management`, `Utilities`, and `Infrastructure` columns while leaving the existing `Media`, `Automation`, and `Downloads` groups intact. `Services` now holds the day-to-day apps, `Management` holds dashboards plus control-plane tools like `n8n` and Changedetection, `Utilities` holds helper/search/conversion tools, and `Infrastructure` now focuses on backing caches, sidecars, and service databases including the Firecrawl Playwright/Postgres/RabbitMQ/Redis stack.

- **Firecrawl self-hosted stack**: Added a new internal-only Firecrawl stack on `chill-penguin` with the upstream API image, Redis, RabbitMQ, `nuq-postgres`, and a repo-owned Playwright sidecar image that patches Firecrawl in-place to launch CloakBrowser directly with `humanize=True`. Wired the new `firecrawl-secrets` bundle and `firecrawl-runtime` projection for `OPENAI_API_KEY`, `POSTGRES_PASSWORD`, and `BULL_AUTH_KEY`, reused the existing internal SearXNG instance at `http://searxng:8080`, projected `FIRECRAWL_URL` plus `FIRECRAWL_API_URL` into Hermes, and added Homepage plus Muximux visibility for `https://firecrawl.ghostship.io`.

- **Firecrawl public tile removal**: Removed the Homepage and Muximux links for `https://firecrawl.ghostship.io` and documented Firecrawl as an internal-only API service with no public web surface.

- **Homepage service regrouping**: Removed stale manager-era Homepage entries from the generated `Services` column, moved `SearXNG`, `BookStack`, `n8n`, and `Changedetection` into `Services`, moved `Firecrawl`, `Firecrawl Playwright`, and `PriceBuddy Scraper` into `Management`, kept `FlareSolverr` in `Utilities`, and pruned the old group placements from the generated `services.yaml`.

- **SearXNG Mojeek removal**: Removed `mojeek` from the enabled SearXNG engine set so the managed rendered config no longer includes it in the active Hermes-facing web pool.

- **Hermes Firecrawl API key projection**: Added a dedicated `FIRECRAWL_API_KEY` to the `firecrawl-secrets` bundle and projected it into Hermes' shared runtime env so Hermes can enable its Firecrawl client path while the internal Firecrawl server continues running without self-host DB auth.

- **Hermes Firecrawl env trim**: Removed the redundant `FIRECRAWL_URL` export from Hermes and kept only `FIRECRAWL_API_URL` for the internal Firecrawl integration contract.

- **Embedded CloakBrowser rollout**: Added repo-owned local image build contexts that embed CloakBrowser into `pricebuddy-scraper` and `changedetection`, replaced PriceBuddy's broken arm64 SeleniumBase sidecar with a repo-owned CloakBrowser Playwright service behind the existing `/api/article` contract, replaced changedetection's manager/CDP dependency with an in-image CloakBrowser Playwright path using `humanize=True`, and added a Firecrawl handoff document for the same binary contract.

- **SearXNG performance-first Hermes tuning**: Replaced the old broad allowlist with a much smaller Hermes-facing pool set, tightened SearXNG's global timeout budget, disabled image proxying, enabled a lightweight Hermes-safe limiter backed by the existing Valkey sidecar, added the persistent `/srv/apps/searxng-cache` bind mount for `/var/cache/searxng`, and replaced the old hand-maintained `settings.yml` mutation path with full managed rendering in `podman-searxng` `preStart` that now requires the existing `SEARXNG_SECRET_KEY` secret instead of generating a random key at startup. Live direct probes promoted `presearch` into the default web pool, while `brave` and `karmasearch` stayed out after immediate `429` and `403` responses.
- **Hermes SOUL persona refresh**: Replaced the default Hermes `SOUL.md` seed with the new Argo persona in the repo and on the live `chill-penguin` runtime so fresh seeds and the current host align on the same assistance and supervision contract.

- **WSL OpenCode desktop service**: Restored a repo-managed
  `opencode-server` Home Manager user service on WSL develop hosts so the
  Windows OpenCode desktop app can attach to `127.0.0.1:4096` over localhost
  forwarding, and removed the repo-managed `ghostship-paseo` daemon startup
  path.

- **Managed brainstorming skill**: Added the standalone
  `obra/superpowers/brainstorming` `skills.sh` install to the develop-host
  maintenance flow so `ghostship-agent-maintenance` keeps it installed and
  refreshed without expanding the repo-managed shared skill inventory.

- **Caveman and workflow retirement**: Removed the managed Caveman default
  behavior from develop hosts, replaced the old Codex Caveman injection with
  declarative cleanup of managed Caveman state, stopped maintenance from
  installing the Caveman Gemini extension or external `skills.sh` Caveman
  skill, and removed the obsolete shared `home/config/workflow.md` /
  `~/.agents/workflow.md` surface.

- **Shared agent instructions rewrite**: Replaced the old global agent prompt
  with the new concise Karpathy-style workflow guidance, removed the unused
  managed `~/.agents/AGENTS.md` target, rewired Codex, Gemini, and OpenCode to
  read directly from the canonical `home/config/AGENTS.md` source through their
  native instruction files, and taught WSL activation to publish the same file
  to the Windows-side Codex Desktop path `%USERPROFILE%\.codex\AGENTS.md`.

- **Hermes current-image runtime refresh**: Removed the stale downstream `CLOAKBROWSER_URL` export so Hermes follows the image-owned native CloakBrowser path, documented `/nix` first-boot seeding plus later default-profile reconciliation, and clarified that the next full Hermes reset must pull the latest published `ghcr.io/ghostship-io/ghostship-hermes:latest` image, wipe persisted auth/XDG/custom-skill/workspace/user-Nix state, rely on bundled upstream default skill seeding, and require fresh Codex auth afterward.
- **Ragenix helper path fix**: Fixed `secrets/rules.nix` to emit rule keys relative to the rules file directory so `secret-edit <logical-id>` and other `ragenix` operations match the tracked `secrets/files/**/*.age` paths again.
- **Managed Paseo daemon and Node FHS wrappers**: Added `paseo` to the same wrapper-plus-maintenance flow used by the other agent CLIs, added a WSL-only `ghostship-paseo` system service that keeps a local daemon on `127.0.0.1:6768` for the Windows desktop app, documented Paseo's current daemon/app version-lockstep expectation, and replaced the broken raw WSL `/usr/bin/npm` plus `/usr/bin/npx` paths with explicit wrapper-backed WSL entries that exec the real Nix store binaries.
- **Develop web service removal**: Removed the managed `opencode-web` and
  `agent-deck-web` user services from the develop/WSL Home Manager profiles, so
  those localhost web daemons are no longer started declaratively on develop
  hosts.
- **Agent Deck maintenance alignment**: Moved `agent-deck` off the flake-pinned package path onto the same wrapper-plus-maintenance flow used by the other agent CLIs, so `ghostship-agent-maintenance` now rebuilds the latest upstream source release with the Ghostship web-mutations patch while the managed CLI remains available for manual use.
- **OpenCode Web UI service fix**: Switched the managed `opencode-web`
  user service to the Nix-provided Node binary instead of the nonexistent
  `/usr/bin/node`, restored an explicit `BROWSER` no-op target, and added
  no-op `xdg-open` plus `xdg-debug` shims so the headless service does not try
  to launch a browser while starting OpenCode. The managed service now runs
  `opencode serve` instead of `opencode web` and binds only to
  `127.0.0.1:4096`.
- **WSL explicit Windows interop contract**: Kept `services.envfs` on WSL hosts for Linux/FHS paths such as `/usr/bin/bash`, disabled automatic Windows PATH import so `envfs` stops synthesizing accidental Windows executables under `/usr/bin`, wrapped `wsl-open` around the real Windows PowerShell path, added a repo-managed `win-powershell` entrypoint, and updated WSL docs to require explicit wrappers or `/mnt/c/...` paths for Windows tools.
- **Dev shell export fix**: Reordered the default flake dev-shell packages to keep `git` before `age`, which avoids the current Nix `2.31.3` order-sensitive `get-env.sh failed to produce an environment` failure while preserving the existing tool set. Refresh `direnv` or start a new shell after pulling the change so the repaired environment export path is used.

- **Hermes default skill seed removal**: Stopped repo-managed default skill seeding for `chill-penguin` Hermes by removing the `skill-creator` copy-if-missing path from `podman-hermes` pre-start so the host now seeds only `SOUL.md` and leaves `/home/hermes/.hermes/skills/` entirely operator-managed by default.

- **Hermes Discord home export**: Added `DISCORD_HOME_CHANNEL=1491229269127598281` back to the `chill-penguin` Hermes container env as an explicit compatibility export while keeping the router/Codex lane contract and five-channel free-response list unchanged.

- **Hermes workstation `main` contract realignment**: Reworked `chill-penguin` Hermes host wiring around the current `ghostship-hermes` `main` image by dropping in-container `systemd` startup, removing host-side `/nix` bootstrap, moving the repo-managed `SOUL.md` and `skill-creator` defaults directly into `/srv/apps/hermes/home/.hermes/`, switching the Discord lane contract to `GHOSTSHIP_ROUTER_CHANNEL` plus `GHOSTSHIP_CODEX_CHANNEL`, rendering `DISCORD_FREE_RESPONSE_CHANNELS` with both pinned lanes and the current three Ghostship free-response channels, and documenting the required destructive stop-reset-start rollout for `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix`.

- **Develop agent stack refresh**: Removed the repo-managed `launch-agent` helper, moved `openspec` onto the same managed auto-update path as `codex`, `gemini`, and `opencode`, made Caveman full the default agent style across Codex, Gemini, and OpenCode, and taught `ghostship-agent-maintenance` to ensure the configured `skills.sh` repos such as `JuliusBrussee/caveman` are installed and updated on each develop host.

- **Direct ragenix edit workflow**: Removed the repo-managed plaintext mirror
  helpers so operator secret changes now happen directly through
  `secret-edit <logical-id>`, with `secret-rekey` reserved for recipient
  changes.

- **Hermes pyLoad API contract**: Switched the Hermes utility env projection
  to follow the new upstream pyLoad contract by sourcing `PYLOAD_API_KEY`
  instead of `PYLOAD_USER` and `PYLOAD_PASS` from `pyload-secrets`.

- **BookStack documentation wiki**: Added a repo-managed BookStack service plus MariaDB sidecar to the `chill-penguin` self-hosted stack, wired the BookStack secret/env surface through the new `bookstack-secrets` bundle, exposed the service in Homepage's `Services` group, added a Muximux tile after Prowlarr, moved Chaptarr into the dropdown before Bazarr, and projected `BOOKSTACK_URL`, `BOOKSTACK_TOKEN_ID`, plus `BOOKSTACK_TOKEN_SECRET` into Hermes through the managed runtime env path. The public `bookstack.ghostship.io` route and the initial in-app setup plus API token creation remain manual follow-up outside the repo-managed bootstrap path.
- **Ragenix secret catalog and host intake redesign**: Replaced `sops-nix` with `ragenix`, moved tracked secret storage to logical-unit `.age` files declared through `secrets/catalog.nix` and `secrets/recipients.nix`, added catalog-driven secret projections for shared consumers, restored the ignored `secrets.dec.yaml` plaintext mirror as the normal operator edit surface via `secrets-edit` plus `secrets-reencrypt`, and redesigned `bootstrap.sh` to capture temporary host-intake bundles with `hardware-configuration.nix` and SSH host `ed25519` keys for Codex-assisted integration.

- **Develop GitHub CLI ownership rollback**: Moved `gh` back to the shared
  develop Home Manager package set and removed the repo-managed WSL `envfs`
  fallback for `/usr/bin/gh` so the repo only promises GitHub CLI as
  develop-profile user tooling.

- **WSL FHS GitHub CLI compatibility**: Extended the WSL `services.envfs`
  fallback path so Windows-side tools such as Codex Desktop can resolve
  `/usr/bin/gh` even when the calling environment does not carry the develop
  profile PATH.

- **WSL FHS shell compatibility**: Enabled `services.envfs` on WSL hosts so
  hardcoded paths like `/usr/bin/bash` exist for Windows-side tools such as
  Codex Desktop when they target the NixOS guest.

- **Hermes single-agent cutover**: Replaced the old `assistant`/`operations`/`supervisor` runtime contract on `chill-penguin` with the upstream single-agent layout rooted at `/home/hermes/.hermes`, switched host wiring to the generic Discord and webhook env contract, stopped emitting any repo-managed browser CDP default, collapsed Hermes seeds to one root `skill-creator` tree plus one Crush Crawfish `SOUL.md`, limited managed CloakBrowser defaults to `Changedetection`, documented the required destructive reset of `/srv/apps/hermes/home`, `/srv/apps/hermes/workspace`, and `/srv/apps/hermes/nix` before first deployment, and aligned startup with the image-owned `ghostship-hermes-startup.service` plus `ghostship-hermes-user-tooling-refresh.timer` path.

- **Hermes Discord allowed users contract**: Switched the Hermes container env wiring from the retired per-profile `DISCORD_*_ALLOWED_USERS` inputs to the single upstream `DISCORD_ALLOWED_USERS` key so the exported Discord auth scope matches the current image contract.

- **Hermes HUD healthcheck**: Switched the Hermes container health probe to use in-container `curl` against `http://127.0.0.1:7681/` so the check follows the upstream HUD endpoint without embedding host-only Nix store paths that do not exist in the image-seeded `/nix`.

- **Develop agent-browser engine pin**: The managed `agent-browser` wrapper
  now defaults `AGENT_BROWSER_ENGINE=chrome` unless callers override it so
  local browser automation keeps using the profile-capable Chrome engine even
  when upstream auto-launch heuristics drift toward Lightpanda.

- **NZBGet UsenetPrime retirement**: Removed the unused `eu.usenetprime.com` backup server from the managed NZBGet config, dropped the retired `NZBGET_SERVER2_*` entries from the local plaintext secret mirror, and reconciled `chill-penguin` so live NZBGet state stops referencing the dead provider.

- **Develop OpenSpec telemetry opt-out**: The managed `openspec` wrapper now
  exports `DO_NOT_TRACK=1` and `OPENSPEC_TELEMETRY=0` by default so successful
  `openspec` commands stop printing harmless PostHog flush stack traces on
  hosts where telemetry egress is blocked.

- **Hermes pyLoad and n8n secret readiness**: Make Hermes wait for
  `pyload-secrets` and `n8n-secrets` before generating
  `/srv/apps/hermes/runtime.env`, and rerun the runtime env sync when either
  secret file changes so bundled utilities keep receiving the current pyLoad
  and n8n credentials.

- **Hermes utility env projection**: Reduced the Hermes container secret surface to `hermes-secrets` plus a generated `/srv/apps/hermes/runtime.env`, projected only the required utility-facing auth values from service-local secret or runtime files, added the missing internal utility URLs including Changedetection, Chaptarr, PriceBuddy, RSS-Bridge, and Synology, and now supply upstream with the generic single-agent Discord and webhook inputs it expects while leaving browser defaults unset so no repo-managed `BROWSER_CDP_URL` or `BROWSER_*_CDP_URL` values are emitted.

- **Synology NFS hard mounts**: Switched the managed Synology NFS mounts on
  `chill-penguin` and WSL hosts from `soft` to `hard` so transient server or
  network stalls stop surfacing as client-side I/O errors during file copies.

- **VueTorrent tunnel binding**: Reconciled qBittorrent's bound interface
  address to Gluetun's live `tun0` IPv4 in the Gluetun monitor, so qBittorrent
  stops getting stuck in a disconnected state after VPN restarts or namespace
  changes when binding by interface name alone is insufficient.

- **VueTorrent startup binding**: Prime `qBittorrent.conf` with Gluetun's live
  `tun0` IPv4 in `podman-vuetorrent` pre-start so qBittorrent no longer boots
  with the previous tunnel address and spends its first restart window unable
  to bind after Gluetun server changes.


- **Develop Gemini maintenance**: Removed the deprecated `experimental.plan` key from the generated develop-host Gemini system settings so managed Gemini launches stop warning about read-only stale config, and added `bash` to the maintenance runtime inputs so npm and npx subprocesses can spawn `sh` reliably during `ghostship-agent-maintenance`.

- **Develop Agent Deck maintenance and WSL web service**: Expose `agent-deck` through the repo-managed wrapper path, let `ghostship-agent-maintenance` refresh it from the latest upstream release, and keep the WSL-only `agent-deck-web` user service on `127.0.0.1:8420`.
- **Develop Workmux removal**: Removed the repo-managed `workmux` package and
  its known user-home artifacts from the supported develop-host workflow.
- **Develop Codex hook cleanup**: Extend the develop-host workmux cleanup to remove the stale `workmux set-window-status ...` commands from `~/.codex/hooks.json`, preserve unrelated valid hooks, warn on malformed hook JSON, and require a Codex or Agent Deck session restart after the relevant rebuild or switch if an old session was still holding the stale state.
- **OpenSpec Ghostship overrides**: `propose` now creates or reuses the change worktree before planning and ends
  with a detailed overview of the proposed change, `apply` now reports completed
  work, proposal updates, and issues found during apply, and `archive` now ends
  with suggested next issues or follow-up work after cleanup.

- fix(self-hosted): pin Gluetun to the live-benchmarked best PIA region, dynamically enumerate that region's current WireGuard servers at selector time, and only fall back to the global PF pool if the primary region disappears

- fix(self-hosted): use Gluetun's native container healthcheck, make Gluetun namespace dependents follow service restarts with `PartOf`/`Requires`, and switch VueTorrent to a local WebUI health probe instead of external `google.com`

### Changed
- **Develop Workmux packaging**: Added a repo-managed `workmux`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative tmux-first worktree orchestration
  without relying on the upstream installer or `cargo install`.
- **Hermes runtime contract**: Aligned the `chill-penguin` Hermes host module with the current single-agent `ghostship-hermes` contract by letting the image-owned startup service and mutable-tooling timer drive internal boot ordering, treating `/home/hermes/.hermes` as the authoritative managed runtime surface, and following the upstream-generated `TERMINAL_CWD=/workspace` root env contract.
- **PyLoad health checks**: Switched the `pyload-ng` container health probe
  from `GET /api` to `GET /favicon.ico` because the current upstream image now
  returns `401 UNAUTHORIZED` on `/api`, which left Podman health checks
  permanently failing and blocked clean NixOS activation.
- **agent-browser bootstrap**: Stopped passing `--with-deps` during develop-host `agent-browser` runtime bootstrap; the Nix wrapper already supplies the needed shared libraries, so maintenance now treats those system dependencies as already packaged instead of attempting unsupported distro package-manager bootstrapping.
- **Codex skill-creator override**: Renamed the shared vendored
  `skills-creator` entry back to `skill-creator`, refreshed the repo-managed
  copy from `vercel-labs/agent-browser` `v0.9.3`, and now reassert the Codex
  built-in `~/.codex/skills/.system/skill-creator` path as a managed symlink to
  `~/.agents/skills/skill-creator` during develop-profile activation and
  `ghostship-agent-maintenance`.
- **Hermes root skill seeds**: Replaced the retired profile-local Hermes `skill-creator` seed copies with one root seed source under `modules/self-hosted/hermes-seeds/skills/skill-creator/`, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/skills/skill-creator/` only when that runtime-owned directory is missing while normalizing the copied tree to writable `apps:apps` ownership and permissions.
- **Gluetun PIA WireGuard selector**: Migrated `chill-penguin` Gluetun from native PIA OpenVPN to Gluetun's custom-provider WireGuard path, added a daily PF-capable PIA server selector that caches the preferred winner under `/srv/apps/gluetun/pia-wireguard-selection.json`, regenerated the runtime env at Gluetun startup, kept PIA VPN-side port forwarding on the persisted `/srv/apps/gluetun` state mount, and updated the monitor to use Gluetun's generic `/v1/portforward` control route while still reconciling qBittorrent/VueTorrent after startup and reconnects.
- **Gluetun selector fast-start benchmark flow**: Renamed the helper to a stable `gluetun-pia-selector` binary, changed `podman-gluetun` startup to trust the cached winner or do only a provisional latency pick, pinned selection to Vancouver, added a post-boot plus 8-hour background selector cycle, benchmarked the top 10 Vancouver port-forward-capable servers with bounded generic HTTPS pulls through temporary Gluetun tunnels, and only restart Gluetun when a challenger is materially faster than the current cached winner.
- **Hermes root SOUL seed**: Replaced the retired profile-local persona files with one root `modules/self-hosted/hermes-seeds/SOUL.md` source, and `podman-hermes` now seeds `/srv/apps/hermes/home/seeds/SOUL.md` only when that runtime-owned file is missing so existing operator edits remain preserved after first seed.
- **Chaptarr book stack**: Added a repo-managed Chaptarr service to the `chill-penguin` arr stack with persisted config, shared `/downloads` access for both torrent and usenet flows, Homepage visibility, and declarative Muximux placement after Bazarr and before `n8n`. Grimmory now mounts both `/mnt/share/Library/Books` and `/mnt/share/Library/Audiobooks` so it remains the first-class consumption surface for the shared library roots, while the public `chaptarr.ghostship.io` route stays part of the external Cloudflare/tunnel workflow.
- **Develop GitHub CLI baseline**: Added `gh` to the shared develop Home
  Manager package set so every develop-profile host gets the GitHub CLI by
  default.
- **Develop Agent Deck packaging**: Added a repo-managed `agent-deck`
  package to the shared develop Home Manager profile through the local Nix
  overlay so develop hosts get declarative multi-agent orchestration tooling
  without using the upstream installer.
- **Bootstrap WSL hostname handling**: `bootstrap.sh` is now tracked as an
  executable script and falls back from `hostnamectl` to `hostname`, avoiding
  the unsupported WSL2 systemd-hostname failure while still changing the live
  hostname during bootstrap. It now also requires an explicit hostname argument
  and requires being run through `sudo`. It emits the matching
  `nixos-rebuild switch --flake .#<hostname>` command and a `nix-shell -p git`
  hint alongside the bootstrap JSON. Durable hostname persistence remains
  declarative.
- **Develop agent maintenance**: Replaced the launch-time `npx` preflight flow
  for `codex`, `gemini`, and `opencode` with installed user-local agent CLIs
  under `/home/nixos/.local/share/ghostship-agent-tools/npm`, added a
  boot-triggered plus 4-hour persistent `ghostship-agent-maintenance` systemd
  timer to upgrade those CLIs and refresh shared skills, Gemini extensions,
  `agent-browser`, and OpenCode's free OpenRouter config, and simplified the
  launchers down to approval-default injection plus direct exec of the
  installed binaries.
- **WSL Nix build fanout**: WSL hosts now cap `nix.settings.cores` at `4` so
  each daemon-dispatched build job cannot claim all reported CPU threads and
  recreate the same memory-pressure stalls inside an `8`-job queue.
- **Login descriptor headroom**: Added a shared soft `nofile` login limit of
  `65536` so shell-heavy local workflows have more file descriptor headroom
  before hitting per-session limits.
- **Global `rg` availability**: Added `ripgrep` to the shared
  `environment.systemPackages` baseline so server-role hosts such as
  `chill-penguin` have `rg` available out of the box.
- **CloakBrowser managed profile set**: Replaced the old default `Direct`
  and `VPN` manager profiles with repo-managed `assistant`, `operations`,
  `supervisor`, and `Changedetection` profiles, and added a host-managed
  keepalive so the `Changedetection` profile is relaunched automatically when
  the manager stays healthy but that profile stops.
- **n8n orchestration stack**: Added a single SQLite-backed `n8n` service for `chill-penguin`, exposed it to Hermes over `ghostship_net`, documented the dedicated `N8N_API_KEY` handoff through `hermes-secrets`, added Homepage visibility, and declared the Muximux dropdown placement immediately after Bazarr with a documented one-time live reorder step on the host.
- **OpenSpec worktree handoff**: The develop-host `openspec` wrapper now keeps
  proposal/design/tasks work on `main`, moves worktree creation or reuse to
  `apply` with the `.worktrees/<name>/` path, and treats `archive` as the step
  that reconciles any matching change worktree back into `main`, commits the
  archive move, and removes the worktree.
- **WSL Nix daemon concurrency**: WSL hosts now cap `nix.settings.max-jobs`
  at `8` instead of inheriting `auto`, which was resolving to `22` on
  `launch-octopus` and letting concurrent flake shells, agent sessions, and
  host builds push `nix-daemon` into multi-gigabyte memory spikes and socket
  stalls.
- **Personal OpenSpec workflow**: Develop hosts now reapply append-only
  Ghostship propose/apply/archive snippets after both `openspec init` and
  `openspec update` so upstream workflow files stay intact while
  main-first planning, root-cause-first debugging, and
  worktree-reconcile-before-archive guidance
  survive refreshes without extra OpenSpec config files.
- **RomM proxy base-path fix**: Muximux's same-origin `/romm/` proxy now
  injects a real document `<base href="/romm/">` for RomM before the app
  boots, which keeps current and future bundles on the correct router base
  even when they ship an empty Vite env object instead of a rewritable
  `BASE_URL` literal. The proxy also now handles RomM's leaked
  `/ws/socket.io/` root websocket path instead of returning a Muximux-side
  `404`.
- **Hermes whole-home runtime**: Updated Hermes to follow the upstream whole-home image contract by mounting `/srv/apps/hermes/home` at `/home/hermes`, `/srv/apps/hermes/workspace` at `/workspace`, and a seeded host path `/srv/apps/hermes/nix` at `/nix` so the bundled Nix store survives container replacement without being hidden behind an empty mount.
- **Hermes `/nix` reseed guard**: Hermes startup now compares the persisted `/srv/apps/hermes/nix` store with the current `ghostship-hermes:latest` system closure and refreshes the mount when that closure is missing, preventing stale `/nix` data from masking the image's bootable store after upstream image updates.
- **Muximux service placement**: Removed Honcho from the generated Muximux tile
  list, moved PriceBuddy back into the Muximux dropdown directly after Bazarr,
  and keep the generated dashboard layout aligned with the retired Honcho
  stack.
- **Honcho retirement**: Removed the Honcho self-hosted stack, dropped Hermes'
  `HONCHO_*` integration wiring and shared Honcho compatibility-state
  management, removed Homepage Honcho entries, and removed the stale
  `litellm-secrets` declaration now that the service is retired.
- **Homepage stale-entry pruning**: Homepage activation now explicitly deletes
  stale `Honcho`, `Honcho Redis`, and `Honcho DB` entries from `services.yaml`
  after `ghostship-config set` so retired services do not linger in the live UI.
- **PriceBuddy token verification**: Normalized the managed
  `pricebuddy-agent.env` bearer rewrite so repeated post-start runs preserve a
  single `id|token` pair, and added host-managed post-start checks for the app
  env files, scraper reachability, and final token format without conflating
  known upstream auth-route or Cloudflare target issues with Ghostship runtime
  wiring.
- **OpenCode programming free-model refresh**: The develop-host `opencode`
  wrapper now refreshes a generated OpenCode config once per UTC day from
  OpenRouter's ranked programming free-model frontend endpoint, stores that
  generated config under the user's state directory, exports `OPENCODE_CONFIG`
  to it at launch, sources the free programming models from that endpoint, and
  rewrites the generated OpenCode model display labels from `(free)` to
  `(ghostship-free)`. The static OpenRouter model maps were removed from both
  Nix-managed OpenCode config paths, which now only retain the explicit
  `permission = "allow"` default.
- **Develop auth cache policy**: Moved the managed `ssh-agent` setup into the
  develop Home Manager profile, switched it to a fixed `/run/user/1000/ssh-agent`
  socket with a `12h` key lifetime, removed the brittle WSL-only post-start
  parser that could leave the user service failed, and made develop-host
  `sudo` credential caching global with a `12h` timeout so fresh agent PTYs do
  not constantly re-prompt while server-only hosts keep the stricter default
  scope.
- **Hermes native image entrypoint**: Removed the repo-side Hermes startup
  shim, entrypoint override, command override, and separate `.honcho` bind
  mount so `chill-penguin` follows the image's native
  `/usr/local/bin/ghostship-hermes-runtime entrypoint` contract while the
  current workstation layout owns the persisted `/opt/data`, `/workspace`, and
  `/nix` mounts.
- **Develop agent launcher defaults**: Develop-host `codex`, `gemini`, and
  `opencode` now declare explicit YOLO or allow-all execution defaults instead
  of relying on mixed upstream behavior; Gemini now applies YOLO through its
  wrapper because upstream `settings.json` no longer accepts that mode.
- **Muximux RomM embedding**: Switched Muximux's RomM tile to a same-origin
  `/romm/` reverse proxy and now install a managed Muximux nginx vhost that
  proxies RomM by service name on `ghostship_net`, because the public
  `romm.ghostship.io` hostname is Cloudflare Access-protected and not a stable
  iframe target.
- **RomM startup hook removal**: Removed the stale `podman-romm` post-start
  bundle rewrite after validating that the upstream RomM `4.8.0` image starts
  cleanly without it; the failing patch target was the source of the live
  startup wedge.
- **RomM iframe shim**: Muximux now injects an iframe-only RomM runtime shim
  ahead of RomM's main module entry instead of rewriting the served RomM bundle
  on disk, and the shim cache-bust is owned by the Muximux config so Chrome can
  be forced onto corrected injection changes without touching RomM assets.
- **OpenSpec init defaults**: The develop-host `openspec` wrapper now injects
  `--tools codex,gemini,opencode --profile core` for `openspec init` unless
  the caller passes explicit `--tools` or `--profile` flags.
- **Shell flake timeouts**: Increased Starship's prompt scan timeout and
  direnv's warning timeout to 30 seconds so slow `use flake` environments have
  more time to initialize before the prompt or warning path gives up.

## [0.1.9] - 2026-04-02

### Removed
- **LiteLLM stack**: Removed LiteLLM and its dedicated Postgres container from the self-hosted stack for now, along with Homepage and Muximux entries and the active `litellm-secrets` declaration. Encrypted secret material in `secrets.yaml` is left untouched until it is intentionally cleaned up.

### Changed
- **Agent memory rewrite**: Rewrote the repo `AGENTS.md` into a shorter
  operating-memory format so it keeps durable repo facts without turning into a
  running debug log, and aligned the shared `home/config/AGENTS.md` preference
  layer with the newer commit/verification/documentation workflow.
- **Shared skill rename**: Renamed the vendored shared `skill-creator` skill to
  `skills-creator` locally while keeping it pinned to the upstream
  `vercel-labs/agent-browser` `skill-creator` package.
- **Python skill defaults**: Updated the shared Python skill to require `src/`
  layout, `uv`, `ruff`, `pytest`, and `basedpyright`, with `ruff format .`,
  `ruff check .`, full-project `pytest`, and full type coverage as the default
  workflow.
- **SSH interaction guidance**: Tightened the shared SSH skill around
  non-blocking tmux-driven remote workflows so prompt-driven commands are
  started in detached tmux sessions and advanced through `capture-pane` plus
  `send-keys`.
- **WSL path guidance**: Updated the shared WSL skill to prefer `/mnt/c/...`
  for Windows files, added `wslpath` conversion guidance, and refreshed the
  PowerShell reference with tested non-interactive patterns for this host,
  including the requirement to use a Windows path with
  `powershell.exe -File`.
- **OpenSpec agent workflow**: Replaced the old Superpowers-based CLI workflow with repo-local OpenSpec scaffolding for Codex/Gemini/OpenCode, exposed an `openspec` CLI wrapper in the shared develop toolchain, and migrated active planning references from `docs/superpowers` to the repo-root `openspec/` tree.
- **Legacy Superpowers cleanup**: Develop-profile activation now removes the old `~/.agents/skills/superpowers`, `~/.gemini/extensions/superpowers`, and `~/.config/opencode/plugins/superpowers` checkouts and prunes Gemini's stale enablement record during activation.
- **Agent launcher preflight**: Standardized the develop-host `codex`, `gemini`, and `opencode` wrappers around a shared `npx` launch flow that refreshes global `skills`, refreshes OpenSpec instructions when launched inside an OpenSpec repo, warns instead of aborting on preflight failures, and keeps Gemini extension updates behind the same warning-only contract.
- **Shared skill curation**: Reduced the repo-managed shared skill inventory to `nix`, `python`, `ssh`, `wsl2`, and the vendored shared `skills-creator` package, removed the local `agent-browser`, `build123d`, and `dispatching-cli-subagents` skills, and rewrote the retained local skills into a leaner modular format aligned with current skills.sh guidance.
- **Flake repo shell**: Added a default Linux `devShell` to the root flake so `.envrc` `use flake`, `direnv`, and `nix develop` all work in the local development environments without changing any host outputs.
- **agent-browser local runtime**: Wrapped the develop-host `agent-browser` command with a Nix-managed browser `LD_LIBRARY_PATH` so Puppeteer's downloaded Chrome can launch on NixOS/WSL instead of failing on missing GTK/NSS/X11/GBM shared libraries.
- **SearXNG direct-network max-open tuning**: Moved SearXNG off the Gluetun network namespace onto `ghostship_net`, switched Hermes to the internal `http://searxng:8080` address, restored the container's default internal port `8080`, replaced the implicit default-engine inheritance with a Nix-managed allowlist plus category/weight overrides, moved SearXNG config generation into `podman-searxng` `preStart` so engine changes restart cleanly, and pruned repeatedly blocked or unstable engines such as Brave, Qwant, Kickass, SolidTorrents, PodcastIndex, Geizhals, Tootfinder, and Semantic Scholar from the live search surface.
- **SearXNG live tuning follow-up**: Re-ran the public Access-protected SearXNG instance through iterative API and browser probes, removed engines that still failed or degraded quality off VPN (`annas archive`, `mojeek news`, `qwant*`, plain `duckduckgo`, and the full Brave family), kept stronger contributors like `mojeek`, `google`, `duckduckgo news/images/videos`, `reuters`, `youtube`, `sepiasearch`, and `bt4g`, and added a Google fallback into the `it` category so agent-style infrastructure queries no longer return empty result sets.
- **SearXNG Brave reinstatement**: Re-enabled `brave`, `brave.news`, `brave.images`, and `brave.videos` in the curated engine allowlist because the active search policy now explicitly favors Brave's independent index coverage over the operational cleanliness gained by pruning its rate-limited engine family.
- **SearXNG autocomplete**: Switched the instance autocomplete backend from `duckduckgo` to `bing` after live benchmarking showed Bing suggestions were faster and more complete for agent-style queries than DuckDuckGo, Startpage, Wikipedia, Mwmbl, or Brave.
- **SearXNG category tuning**: Rebalanced the curated engine set around the current agentic-search priorities by enabling Bing web search, Repology package search, Apple Maps, Google Play Apps, Erowid, Moviepilot, and additional icon engines, removing `hoogle` and `gentoo`, promoting Reuters/Google News/YouTube/Wikipedia in their respective categories, and narrowing package, software-wiki, app, movie, and icon engines to the categories where they provide the strongest signal.
- **SearXNG category tuning follow-up**: Dropped `svgrepo` again after live icon probes immediately hit rate limits, and raised per-engine timeouts on the slower app, package, icon, and Erowid sources so the engines explicitly kept for those categories have a chance to contribute before the global request cutoff.
- **SearXNG package and other cleanup**: Removed `duckduckgo weather` after repeated live `400` errors on non-weather queries, pushed package search harder toward `pypi`, `repology`, and Alpine, and demoted the long tail of ecosystem-specific package registries into `it` so package-name lookups are less dominated by unrelated exact-name matches.
- **SearXNG PyPI engine override**: Replaced the upstream PyPI HTML scraper with a local exact-match engine mounted into the container that uses PyPI's JSON API, and marked curated engines `inactive = false` so default-off engines like `repology` can be activated reliably from the repo-managed engine list.
- **SearXNG weather source swap**: Replaced `openmeteo` with `wttr.in` in the curated weather category after live tests showed the old weather path returning no useful answers while wttr's upstream JSON endpoint remained healthy.
- **Global Bash defaults**: Moved Bash completion and baseline readline/history behavior into the shared NixOS layer so all Bash shells, including root, now get `bash-completion`, case-insensitive ambiguous completion, cleaner history handling, incremental history writes, and `checkwinsize` by default.
- **CloakBrowser healthcheck**: Replaced the `wget --spider` Podman probe with a Python `urllib` GET against the local manager endpoint, because the current image on `chill-penguin` serves the app correctly but still reports repeated false-negative healthcheck failures under the `wget` runner.
- **Host role refactor**: Added explicit `ghostship.host.roles` booleans, split WSL into its own top-level module area, and moved Home Manager into `base`, `server`, `develop`, and `wsl` profile layers. Server-role hosts now default to `bash`, develop-role hosts default to `fish`, and the package split is cleaner between system packages and user packages.
- **Flake host construction**: Consolidated repeated `nixosSystem` wiring behind a shared `mkHost` helper and removed the unused `nixpkgs-unstable` input.
- **Self-hosted inventory consistency**: Reordered the flat self-hosted module inventory into documented category blocks and removed the last non-Plex host port exposure by keeping CloakBrowser on internal networking with the standard Podman healthcheck cadence.
- **Workflow docs**: Rewrote the local workflow guidance to match the actual repo workflow instead of the old `plan.md`-driven process.
- **Docker Hub auth support**: Added a `dockerhub-secrets` bundle and runtime auth-file generation so the self-hosted Podman stack can authenticate Docker Hub pulls instead of hitting rate limits during restart-time updates.
- **Docker Hub placeholder fallback**: The Docker Hub auth hook now writes an empty `auths` file when the secret bundle still contains the placeholder values, so public pulls can continue anonymously instead of failing the whole stack during deploy.
- **Podman auto-update**: Every self-hosted OCI container now sets `pull = "always";` and carries Podman's registry auto-update label, and a daily native `podman auto-update` timer refreshes changed images in place. Failed restarts are still surfaced through systemd/journal for now.
- **WSL `/mnt/z` NFS mount**: Replaced the WSL-only `Z:`-backed SMB mount script with a direct Synology NFS automount at `/mnt/z`, reusing the tuned `chill-penguin` mount options so access is faster on-network and fails gracefully when the NAS is unavailable or the host is off-network.
- **WSL `/mnt/z` activation reset**: WSL activation now stops the `/mnt/z`
  automount and unmounts any live NFS mount before reloading the generated
  mount units, so host switches do not fail on stale `/mnt/z` mount state.
- **PyLoad healthcheck**: Switched the PyLoad container health probe from `/` to `/api`, because the current web UI config can leave the root path in an internal redirect loop even while the service itself is healthy.
- **LiteLLM database startup**: LiteLLM now writes a runtime env file that maps the existing secret bundle onto the `DATABASE_URL` variable the upstream image actually uses, and the Postgres side now writes a real `POSTGRES_PASSWORD` runtime env file instead of passing the literal `env:LITELLM_DB_PASS` marker through to the container. The LiteLLM Postgres unit also reconciles the `litellm` role password from secrets on startup so older initialized volumes converge to the current secret. This allows Prisma migrations to run and fixes the LiteLLM UI's `Not connected to DB!` login failure on `chill-penguin`.
- **LiteLLM ChatGPT subscription wiring**: LiteLLM now mounts a persistent ChatGPT OAuth token directory and ships a proxy config for the current `chatgpt/` provider models (`gpt-5.4`, `gpt-5.4-pro`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.3-instant`, and `gpt-5.3-chat-latest`) so ChatGPT-subscription-backed models can be added without API keys and keep their OAuth session across container restarts.
- **Native Nix docs**: Updated the repo documentation and agent instructions to use native `nix`, `nixos-rebuild`, and `switch-to-configuration` commands instead of `nh`.
- **CloakBrowser native origin patch**: Replaced the custom aiohttp proxy with a startup patch against the upstream manager's `AuthMiddleware`, so the app now strips incoming `Origin` headers at the ASGI boundary and keeps the native VNC/CDP WebSocket handling intact.
- **PyLoad config application**: `ghostship-config` now recognizes `pyload.cfg` as PyLoad's typed config format and updates the existing section/key lines in place, so the PyLoad activation settings actually take effect instead of being appended as invalid `section.key=value` lines.
- **PyLoad NFS startup**: Restored the LinuxServer image's supported root-run startup mode and replaced the broken `fix-attrs/down` override with a narrow patch to `init-pyload-config/run` that keeps `/config` ownership handling but skips the `/downloads` `chown` on the NFS share.
- **Documentation Migration**: Merged `GEMINI.md` into `AGENTS.md` and removed devenv references from `README.md`. Added self-hosted services overview.
- **ghostship-config YAML Upserts**: Fixed Homepage-style list-group creation in `ghostship-config.py` so paths like `[Utilities].[OmniTools].icon` create missing groups with the correct list container and pass the script self-tests again.
- **Homepage resources widget typing**: The Homepage activation script now writes the resources widget's `cpu`, `memory`, and `network` options as native YAML booleans instead of quoted strings, which restores the network bandwidth section instead of showing `API Error`.
- **Homepage network stats mount**: Homepage now keeps the resources widget pinned to `end0` on `chill-penguin` and mounts only the network-related sysfs paths needed to resolve `end0`'s host symlink target, avoiding the broken `/sys/class/net` links without exposing the wider `/sys` tree that made Homepage's disk probe fail.
- **RomM iframe startup hook**: Added a `podman-romm` `postStart` hook that patches RomM's routed iframe crash trigger in the active hashed frontend bundle and cleans up temporary debug assets created during live investigation.
- **VueTorrent LSIO integration**: Replaced the hand-managed VueTorrent zip extraction with the official `ghcr.io/vuetorrent/vuetorrent-lsio-mod` on the LinuxServer qBittorrent image. The service no longer forces `-u 3000:3000`, the stale manual `/srv/apps/vuetorrent/ui` state is removed during activation, and qBittorrent is configured to use `/vuetorrent`, avoiding the recurring `Unacceptable file type, only regular file is allowed.` failure.
- **Gluetun PIA compatibility**: The `podman-gluetun` `preStart` hook now mirrors legacy `OPENVPN_PASS` into `OPENVPN_PASSWORD` before writing `/run/secrets/gluetun-runtime.env`, keeping the current Gluetun image compatible with the existing secret bundle on `chill-penguin`.

### Added
- **SSH workflow references**: Added shared SSH skill references for common
  tmux background patterns and interactive SSH command patterns.
- **Honcho stack**: Added a local Honcho stack for Hermes using one s6-supervised app container plus database and Redis sidecars, wired Hermes to generate `~/.honcho/config.json` at startup, and added Homepage and Muximux entries.
- **RSS-Bridge and PriceBuddy**: Added internal-only RSS-Bridge and PriceBuddy services to the Ghostship stack, wired both into Homepage's Services column, added the PriceBuddy MySQL/scraper sidecars, and sourced the persistent PriceBuddy agent API token from the `pricebuddy-secrets` bundle.
- **PriceBuddy env bootstrap**: Moved PriceBuddy env-file generation into the service start path so the MySQL and app containers can see `/srv/apps/pricebuddy/{pricebuddy.env,pricebuddy-db.env,pricebuddy-agent.env}` reliably after secrets are installed.
- **PriceBuddy bearer format**: The persisted agent token now writes a shell-safe `PRICEBUDDY_API_TOKEN="id|token"` bearer line into `/srv/apps/pricebuddy/pricebuddy-agent.env` so non-interactive API calls authenticate correctly.
- **PriceBuddy process env**: Restored PriceBuddy's app `environmentFiles` so the upstream `start-app.sh` sees the DB host and credentials it waits on before Apache starts.
- **Nix command reference**: Added a native Nix command reference under the Nix skill with build-first, no-`sudo`, and `chill-penguin` deployment guidance.
- **Hermes service**: Added a new `ghcr.io/ghostship-io/ghostship-hermes:latest` self-hosted service with Homepage and Muximux entries, internal service URL wiring for the existing stack, RomM/Grimmory secret imports for `*_USER` / `*_PASS`, and a named Podman volume for `/nix` so the image keeps its bundled entrypoint store.
- **ghostship-config Utility**: A self-verifying, idempotent configuration manager for surgical updates to XML, YAML, INI, and KV files. Supports secure secret injection via environment/file references.
- **Pure Surgical Migration**: Migrated all self-hosted services (Sonarr, Radarr, Plex, Homepage, etc.) to a pure surgical configuration model, removing all full-file templates and enforcing the "Ghostship Standard" for identity and privacy.
- **Unified Agent Tooling**: Added a shared `~/.agents`-based skill/instructions model and a Gemini delegation MCP server for repo research and plan generation across Gemini, OpenCode, and Codex.

## [0.1.8] - 2026-03-20

### Removed
- **Agent Browser Skill**: Removed the `agent-browser` Gemini skill definition. The `agent-browser-mcp` server remains active for tool-based browser automation.

## [0.1.7] - 2026-03-19

### Added
- **SSH Skill**: Created a new Gemini skill for advanced remote server management based on `mcp-ssh-manager`.
- **Agent Browser Skill**: Created a new Gemini skill for token-efficient browser automation via `agent-browser-mcp`.

### Changed
- **SSH MCP**: Swapped `@aiondadotcom/mcp-ssh` for `mcp-ssh-manager` by `bvisible` for enhanced remote management capabilities.
- **Browser Automation**: Swapped `browser-use` for `agent-browser-mcp` to leverage token-efficient accessibility trees and semantic locators.

## [0.1.6] - 2026-03-18

### Changed
- **Gemini Template**: Overhauled `home/config/gemini.md` to follow 2026 Open Source Software (OSS) best practices.
- **Workflow**: Updated Conductor `workflow.md` to prioritize autonomous verification and report results.
- **Policies**: 
    - Established "Open Source Excellence" as a baseline for all projects.
    - Added "Continuous Learning" as a HIGH PRIORITY directive to record mistakes and new discoveries in project memory.
    - Prohibited `save_memory` in favor of centrally managed cross-project memory via user prompts.
    - Prioritized `nh` for all supported system operations.
    - Updated TDD policy to prioritize unit/integration tests for applications and test environments for infra/config.

## [0.1.5] - 2026-03-11

### Added
- **Python Skill**: Added a new Gemini skill for modern Python development using `uv`, Nix flakes, `black`, `isort`, and `pyright`/`pylance`.

## [0.1.4] - 2026-03-11

### Added
- **SSH MCP**: Added `mcp-ssh` for remote task execution via `@aiondadotcom/mcp-ssh`.
- **Browser Automation**: Switched from `playwright` to `browser-use` MCP using `mcp-browser-use`.
- **Gemini Extension**: Installed `richardcb/oh-my-gemini` for advanced workflow orchestration.
- **System Packages**: Added `uv` to common system packages for MCP runners.

## [0.1.3] - 2026-03-11

### Changed
- **Gemini Config**: Enabled the experimental `plan` mode in `modules/develop/gemini.nix`.

## [0.1.2] - 2026-03-10

### Added
- **Host Bootstrap Script**: Implemented `bootstrap.sh` for initial host setup, age key generation, and hardware configuration capture.
- **Host Registration**: Added `register-host` CLI tool to automatically integrate new hosts (updating `.sops.yaml`, creating host directories, and re-encrypting secrets).
- **Documentation**: Added comprehensive "Bootstrap a New Host" section to `README.md`.

## [0.1.1] - 2026-03-09

### Added
- **System Skill Update**: Added `nh os build` to the Command Reference Matrix for testing NixOS configurations.

## [0.1.0] - 2026-03-09

### Added
- **Automated Maintenance**: Configured automated daily Nix garbage collection and system generation pruning (keeping 7 days) in `modules/common/default.nix`.
- **Maintenance Documentation**: Added a "Maintenance & Cleanup" section to `README.md` with instructions for `nh clean`.
- **System Skill Update**: Reinforced the "Documentation Mandate" and added "Versioning & Conductor" autoincrement logic in `home/config/skills/system.md`.
- **Version Tracking**: Created the `VERSION` file and initialized it at `0.1.0`.
- **Initial Changelog**: Created `CHANGELOG.md` to track project evolution.

### Changed
- **Config Apply Workflow**: Updated documentation to prefer `nh os switch` over `nixos-rebuild`.
- **Memory Policy**: Updated `AGENTS.md` to track the new maintenance automation.
