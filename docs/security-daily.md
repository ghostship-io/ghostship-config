# Daily security maintenance

The existing campaign task runs at 09:00 UTC and points here. Reuse it and
campaign issue #102; reconcile open work before changing source. Follow the
installed `ghostship-engineering` skill and current `routing-policy.md` for
review, landing and deployment. Security evidence and private configuration
stay off free-tier workers. Report only completed work or blockers to the
current orchestrator.

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
3. Advance relevant fixes in the existing feature branch. Prefer a stable
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
   The current program rollout has owner authorization after exact-revision,
   review, privacy and continuity gates. Future automatic work prepares and tests
   fixes but retains its human deployment gates. Apply through committed Git and
   the existing activation helper only within the applicable authorization. Follow the
   [session guard](container-workflow.md#preserve-the-active-t3-code-session).
   Material compatibility decisions, exposure, reboot,
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
