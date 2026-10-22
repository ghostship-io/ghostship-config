# Daily security maintenance

The existing campaign daily task runs at 09:00 UTC. Its native prompt points
here; this file owns the procedure. Reuse the existing task and campaign issue
#102. Coordinate shared refs, deployment windows and history changes with the
current program coordinator and privacy owner. Reconcile active workers and
open PRs before starting work; continue their packages rather than duplicating
initiators. Use free models only for low-complexity work. Route complex package,
network and containment implementation to an available capable recent Flash model
with its advertised reasoning setting; keep frontier review with the lead.
Checkpoint accepted writes and active builds before changing the same owner's
model selection, then read back the route. Preserve its thread/worktree and avoid
duplicate workers or restarting active T3/provider processes.

## Updates and exploit mitigation

1. Discover the current checkout, remote refs, deployed system and booted kernel,
   active container IDs/start times, package derivations and image digests.
   Inspect host and container update timers, their effective commands, last
   results and owners. Include Nix clients **and running daemons**, Podman,
   OCI runtimes, containerd/Docker, kernel modules, public-facing applications,
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
3. Automatically advance relevant fixes: reuse an existing owner/PR or delegate
   a bounded implementation in an isolated worktree. Prefer a stable patch release
   or verified backport over a broad dependency upgrade. Prepare reproducible
   candidates, compare source/patch identity, run meaningful harmless regression
   and canary checks, and run `nix develop .#ci -c scripts/check`. Stage new Nix
   files before evaluation. Update release metadata for the delivered change.
   Keep active T3, its inner runtime and provider processes intact. Use separate
   disposable candidates; never execute an exploit against production.
   Before integration, the frontier lead reviews and repairs bulk output,
   including test quality, affected consumers/services, blast radius, security
   and environment contracts, and required canonical docs/skills. Keep tests
   load-bearing; reject mirrored, brittle or weakened checks. OpenCode review
   alone is insufficient. The current coordinator is the final frontier gate
   for shared integration; reuse that gate rather than creating duplicate reviewers.
4. Before application, inspect the complete activation/unit diff and existing
   maintenance locks. Inspect `/run/ghostship-security-continuity/hold` and
   the deploy service's loaded `zz-ghostship-owned-security-continuity.conf`
   drop-in. If present, report its protected ownership record and pending-image
   status in the existing campaign checkpoint; retain it until the coordinator
   reviews the destination and active sessions. Do not release it as routine
   cleanup or restore an old queue snapshot over a newly queued request.
   Recheck candidate output registration, NAR identity and owned GC roots:
   successful `--no-link` builds may have been collected since testing.
   Account for daemon/build continuity, indirect container
   restarts, image retags, rollback artifact availability and scheduled writers.
   The current program rollout has owner authorization after exact-revision,
   review, privacy and continuity gates. Future automatic work prepares and tests
   fixes but retains its human deployment gates. Apply through committed Git and
   a coordinated window only within the applicable authorization. Follow the
   [session guard](container-workflow.md#preserve-the-active-t3-code-session).
   Shared main/switch/history mutations require coordination, not a new generic
   approval request. Material compatibility decisions, exposure, reboot,
   destructive migration and unresolved broad enforcement retain their owner
   gates. Preserve the absolute active-T3 session guard even if an updater
   ordinarily permits an idle restart. Advance independent preparation while
   an activation gate is pending.
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

## Completion

Post one public-safe #102 checkpoint when material state changes: checked
coverage and unknowns, official sources, applicability, PR/commit/check results,
prepared versus applied versus runtime-verified state, rollback, profile learning
credit, containment results, remaining exposure and next action. Report categories
and paths instead of private identities, coordinates, payloads or raw records.
Check names and labels can also contain coordinates: export reviewed categories
and counts, rather than assuming that removing a detail field sanitizes a report.
Send shared-state decisions to the current coordinator. Update the issue plan
when phase state changes. A run is complete only after it advances an actionable
fix or records the concrete gate and independent work completed.
