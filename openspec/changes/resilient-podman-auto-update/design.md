## Context

The self-hosted stack on `chill-penguin` uses native Podman auto-update through
a shared systemd service and timer defined in `modules/self-hosted/common.nix`.
Each container is labeled for registry-based auto-update, and Podman already
performs the desired per-container pull and restart logic. The current
limitation is the top-level service contract: if one updated container fails to
restart, `podman auto-update` exits nonzero and the shared unit is marked
failed, even when other containers updated successfully.

The user wants the scheduled updater to stay green for partial failures, keep
the existing randomized delay behavior, and move the update window to 04:00.
The ongoing RomM-specific restart issue is out of scope for this change.

## Goals / Non-Goals

**Goals:**
- Preserve native Podman update behavior for labeled containers.
- Treat per-container restart failures as partial failures rather than total
  updater failure when Podman returns trustworthy per-unit results.
- Keep journald visibility for failed units so operators can still see which
  containers failed during the run.
- Schedule the timer at `04:00` with the existing 30-minute randomized window.

**Non-Goals:**
- Fix container-specific restart failures such as the current RomM issue.
- Introduce notification delivery, dashboards, or alert routing.
- Replace Podman with a custom pull/recreate engine.
- Change container-level auto-update labels or image selection policy.

## Decisions

### Decision: Wrap native `podman auto-update` instead of replacing it

The updater will remain a thin wrapper around native `podman auto-update`.
Podman already understands the container labels, pull rules, rollback
semantics, and systemd integration used by this repo. Reimplementing the
per-container update flow in shell would duplicate Podman's own behavior and
increase drift risk.

Alternative considered:
- Custom per-container update loop. Rejected because it would duplicate native
  Podman logic, make rollback semantics harder to trust, and require more repo
  maintenance.

### Decision: Use structured output to distinguish partial failures from hard failures

The wrapper will invoke `podman auto-update --format json` and parse the
results. If Podman returns structured per-unit statuses, container rows marked
`failed` will be treated as partial failures: the wrapper will log a concise
summary naming the failed units and exit successfully. If Podman fails before
returning usable structured output, the wrapper will preserve the nonzero exit
status so auth, registry, or command-level failures still surface as real
updater failures.

Alternative considered:
- Mark Podman exit code `125` as success in systemd. Rejected because Podman
  uses that code for multiple failure modes, including failures that should
  still fail the updater.

### Decision: Keep failure visibility in journald

The wrapper will emit a warning summary for failed units to journald rather than
silencing partial failures. This preserves operator visibility without forcing
the timer into a failed state for every single bad container update.

Alternative considered:
- Ignore failed units silently. Rejected because it would hide real service
  regressions and make auto-update behavior harder to audit.

### Decision: Change to a fixed 04:00 timer while preserving jitter

The timer will move from `daily` to `*-*-* 04:00:00`, and
`RandomizedDelaySec = "30m"` will remain. This preserves the user's preferred
quiet-hours schedule without causing every update to start at the exact same
second after host activation.

Alternative considered:
- Remove the randomized window. Rejected because the user explicitly wants to
  keep it.

## Risks / Trade-offs

- [Partial failures no longer fail the unit] -> Mitigation: log failed units
  explicitly in journald and keep hard failures nonzero when no trustworthy
  result set is available.
- [Wrapper depends on Podman's JSON output shape] -> Mitigation: keep the parser
  narrow and based only on documented fields (`Unit`, `Image`, `Updated`).
- [A failed container may be overlooked if nobody checks logs] -> Mitigation:
  preserve concise warning output so later notification work can hook into the
  same summary.
- [Timer still does not provide immediate post-publish updates] -> Mitigation:
  accepted trade-off; this change only improves resilience and timing, not
  update cadence beyond the scheduled window.

## Migration Plan

1. Add a small wrapper script in `modules/self-hosted/common.nix`.
2. Point `podman-auto-update.service` at the wrapper instead of invoking Podman
   directly.
3. Change the timer schedule to `*-*-* 04:00:00` and keep
   `RandomizedDelaySec = "30m"`.
4. Document the new semantics in repo docs and agent memory.
5. On the host, apply the updated system configuration so systemd reloads the
   service and timer definitions.

Rollback is straightforward: restore the previous direct `podman auto-update`
service command and `daily` timer expression, then switch the host back to the
prior generation.

## Open Questions

- None for the initial change. Notification routing and container-specific
  retry policy remain follow-up work.
