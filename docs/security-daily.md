# Daily security maintenance

Each daily check starts in a fresh session and finishes after one bounded run.
Discover the current orchestrator and its unfinished-work checklist before acting.
Read this procedure, the installed `ghostship-engineering` skill and current
`routing-policy.md`; each run must discover its own source and live state without
relying on an earlier session. Reconcile existing findings and feature ownership
before starting a fix. Send findings and concrete blockers to the orchestrator,
which assigns follow-up work. The daily session has no permanent ownership.

The orchestrator manages the single daily security task. Inspect its existing
schedule; this procedure never creates another schedule, recurring campaign or
permanent security thread. Keep private security evidence off free-tier workers.

## Updates and exploit mitigation

1. Discover the current checkout, remote refs, deployed system and booted kernel,
   active container IDs/start times, package derivations and image digests.
   Inspect host and container update timers, their effective commands, last
   results and owners. Include Nix clients **and running daemons**, Podman,
   OCI runtimes, kernel modules, public-facing applications,
   Agent Desktop/browser, provider tools and model refresh. Reuse the configured
   host auto-upgrade, Podman auto-update, desktop canary updater, T3 tool/provider
   maintenance and model refresh owners. Record failed or unknown coverage;
   a mutable image tag is not an installed application version. Keep raw
   inventories, private source coordinates and identifying values private.
2. Fetch current official vendor advisories and the CISA KEV feed. Map each
   relevant finding to the **installed artifact**, source revision, derivation
   patches and documented exploit preconditions. Separate affected, patched,
   not applicable and unverified. Version comparisons are leads when backports
   are possible. Check the running kernel separately from the next-boot kernel.
   Prioritize escape, root/API sockets, mount trust, privileged capabilities and
   seccomp, exposed RCE, lateral movement/exfiltration and resource exhaustion.
   Preserve uncertain findings as work; an advisory is not evidence of intrusion.
3. Advance an assigned bounded fix in its existing feature branch; report other findings
   to the orchestrator for assignment. Prefer a stable
   patch release or verified backport over a broad dependency upgrade. Prepare
   reproducible candidates and compare source/patch identity. Run fast unit
   regressions before merge; integration checks run in GitHub after merge.
   Stage new Nix files before evaluation. Use the landing tool for release
   metadata. Frontier authors self-review the exact diff; worker changes need
   one frontier review. Record that revision with `agent review approve`, then
   use `agent pr land`. Review affected consumers, privacy, test quality and
   deployment impact. A patch-identity marker is not an executed vulnerability
   regression. Keep production exploit execution out of the procedure.
4. Before application, inspect the complete activation/unit diff and existing
   maintenance locks. Read the pending deployment destination and any existing
   inhibition with its ownership record. Preserve unrelated controls and never
   restore an old queue snapshot over a newly queued request.
   Recheck candidate output registration, NAR identity and owned GC roots:
   successful `--no-link` builds may have been collected since testing.
   Account for daemon/build continuity, indirect container
   restarts, image retags, rollback artifact availability and scheduled writers.
   Apply assigned fixes through committed Git with `agent deploy run`, preserving
   its busy-session guard. Follow the
   [session guard](container-workflow.md#preserve-the-active-t3-code-session).
   Material compatibility decisions, exposure, reboot, destructive migration and
   unresolved broad enforcement retain their owner gates. Advance independent
   preparation while an activation gate is pending.
5. After application, read the running executable/daemon/image and effective
   policy again. Verify source fixes or containment, service compatibility,
   health and the preserved T3 identity. Prepared source, a successful build,
   a next-boot artifact and an actually patched runtime are separate states.
   If verification fails, use the reviewed rollback scoped to this change;
   preserve evidence and report remaining exposure. For module containment,
   see [kernel mitigation](kernel-exploit-mitigation.md).

## Confinement and network review

Use [AppArmor learning policy](plex-apparmor.md) and [SIEM procedure](siem.md).
Check the existing 08:30 collector; refresh only when stale. Keep raw evidence
under its protected evidence directory. Inspect every container's host PID
label, loaded mode, configured profile, image/source identity, audit heartbeat,
lost counters and journal continuity. A boot, switch, policy/image change,
collection gap or confinement failure resets that profile's learning window.
Credit only seven full verified unchanged days with representative workloads
and no unresolved legitimate violations. Startup, playback/transcode, subtitles,
scans, metadata, integrations, updates and maintenance need coverage; idle time
alone does not qualify. Prepare an enforcement PR and evidence checkpoint
before enforcement. AppArmor cannot inspect argv or inline source; isolate
interpreters and grant only independently verified legitimate resources.
Never turn attacker-influenced audit text into new allow rules.

Review configured dependencies and observed flows separately. Classify new
edges; observations do not authorize connectivity. Advance reviewed per-container
containment with candidate allow/deny packet tests, including same-bridge,
routed host/private, DNS, egress, IPv6 and bypass paths. Preserve unresolved
production dependencies as gates. Check Access, tunnel and DNS drift without
adding exposure; report unavailable router/IPv6 evidence as unknown.

Check security-monitor health, failed units, listeners, root/API socket mounts,
capabilities, seccomp, SSH/config drift, persistence and authentication anomalies.
Use existing notification helpers/owners for security delivery. Investigate
possible intrusions under the SIEM campaign rules before changing detections.

Use `agent capabilities search 'SIEM investigation' --json` to discover the
read-only investigation owner, then `agent siem` for alert evidence:

- `agent siem sensitive-reads --at "$timestamp"` categorizes sensitive file
  reads, recorded process ancestry and unit roles around the alert.
- `agent siem unit-session --unit "$unit" --at "$timestamp"` correlates the
  unit's PAM, session and audit records. Use the unit from protected host
  evidence or runtime configuration; output aliases are per-call roles.
- `agent siem container-health` checks Podman call timeouts, current runtime
  lock waits and snapshot age without calling the possibly stalled runtime.
- `agent siem query --query "$logsql" --start "$start" --end "$end"` runs a
  free LogsQL investigation in an explicit bounded window.

Default output gives categories, counts and verdict hints; `--json` adds
redacted detail. Queries and raw evidence stay on the host; even arbitrary
query field names and values become role aliases. Narrow windows when a row
or detail budget is reached. Distinguish absent evidence, retention gaps and
bounded samples from clean results. PAM success alone does not prove a read
legitimate, and one fresh snapshot does not establish sustained recovery.

## Completion

Include a public-safe checkpoint in the orchestrator report: checked
coverage and unknowns, official sources, applicability, PR/commit/check results,
prepared versus applied versus runtime-verified state, rollback, profile learning
credit, containment results, remaining exposure and next action. Report categories
and paths instead of private identities, coordinates, payloads or raw records.
Check names and labels can also contain coordinates: export reviewed categories
and counts, rather than assuming that removing a detail field sanitizes a report.
Send one self-contained findings report to the orchestrator with severity, observed
evidence, existing owner or proposed bounded fix, concrete blockers and verification
state. Link the existing tracking issues and reconcile their open items. End the session after
reporting; follow-up ownership and the next daily run belong to the orchestrator.
