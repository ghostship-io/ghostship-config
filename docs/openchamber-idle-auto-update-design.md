# OpenChamber Idle Auto-Update Design

## Goal

Keep OpenChamber and OpenCode on their npm `latest` releases without stopping
or restarting work that is currently running.

## Tool generations

The four-hour updater resolves `@openchamber/web@latest` and
`opencode-ai@latest` at run time. It installs the resolved pair into a new
generation rather than changing the active commands in place. npm lifecycle
hooks and candidate probes run without production secrets, home data, workspace
data, shares, or daemon sockets inside a Bubblewrap namespace. The updater and
locked promotion validator are also bounded to 4 GiB of memory and 512 tasks;
the same limits cover fresh bootstrap and the legacy migration prestage.

Each generation records both upstream versions and the OpenChamber harness
revision. The harness revision forces a new candidate when local admission or
recovery logic changes but the upstream versions do not. A candidate is parsed,
smoke-tested, root-owned, made read-only, and revalidated while the promotion
lock is held. Only an atomic `active` symlink change exposes it.

## Admission and drain protocol

The maintenance worker creates a root-owned admission gate. A patched
OpenChamber runtime then:

1. Rejects new mutating HTTP requests and WebSocket upgrades.
2. Pauses the scheduled-task dispatcher before it claims more work, preserving
   queued tasks for resume.
3. Counts in-flight mutations, terminal sessions including pending PTY creates,
   OpenCode task sessions, pending goal continuations and audits, and already-running scheduled tasks.
4. Stops reconnectable observer streams after task-bearing work drains.
5. Leaves existing terminal and task connections intact while they finish.

The worker also adds a narrow OpenCode output-chain rule that rejects only new,
non-root TCP connections to the managed OpenCode port. Existing connections are
allowed to drain. Promotion requires all OpenChamber counters to reach zero,
`/api/session-activity` to report only idle sessions, OpenCode session status to
be idle, and direct OpenCode connections to be gone for 30 continuous seconds.
A failed or unknown probe always defers maintenance.

After the coordinated service restart, ordered health checks must pass before
the candidate is recorded as active. Failure re-establishes the gates, drains
again, and restores the previous generation. Interrupted promotions retain a
transaction record so recovery restores the old generation before accepting
new work. A failed release is not retried until npm exposes a newer pair or the
harness revision changes.

Health recovery uses the same admission and drain protocol. A missing managed
OpenCode process is treated as safely absent, allowing the coordinated restart
to recover it; an existing process must still be idle with its connections
drained. When an external OpenCode service survives a stopped web service,
container health queues this coordinated recovery and defers Podman's kill
policy instead of preempting direct OpenCode sessions.

## Container image deployment

Host activation writes a content-derived desired image identity without
restarting the running container. A one-minute host worker applies a changed
image only after the same OpenChamber and direct OpenCode drain checks pass.
It records the exact previous Podman image ID before stopping the container.

The new image must reach Podman healthy state, an active web service, and a
reachable root endpoint before its identity becomes applied. On failure, the
worker re-quiesces a reachable replacement. If the replacement web service is
inactive or failed and never exposed HTTP, it gates direct OpenCode admissions
and proves OpenCode idle or absent before restoring the previous image. The
previous image ID and failed desired identity persist across boots, and a
temporary systemd override prevents the normal image preload from replacing the
rollback tag. Restoration is retried until the old image is healthy before the
failed desired image is latched. A newly changed or reverted desired identity
cannot discard that state; the exact-image rollback completes first and the next
timer invocation starts from the last verified image.

The first transition from a legacy image cannot prove terminal or scheduler
drain because that runtime lacks the maintenance counters. It prestages the
latest validated generation but deliberately requires one operator-controlled
stop. Once the gated runtime is active, later tool and image updates are fully
automatic.

Provider retry monitoring logs prolonged retries without aborting sessions.
Rate limits and transient provider outages therefore remain recoverable by
the runtime instead of being cancelled after ten minutes.

`ghostship.openchamber.goalMaxAutoTurns` defaults to 1,000 automatic goal
continuations, replacing the upstream 20-continuation ceiling for multi-day
work. Per-goal token budgets, completion/blocked audits, and manual Stop remain
effective. This increases potential provider usage; it is a continuation count,
not a guaranteed runtime duration.

## Runtime boundaries

OpenChamber remains the aggregate task authority through
`/api/session-activity`, augmented by explicit counters for work that is not
fully represented there and by direct inspection of the managed OpenCode
server. Observer-only SSE and WebSocket streams are reconnectable and do not
block maintenance after task-bearing work has drained.

The web workload remains in a bounded cgroup with `MemoryHigh=32G`,
`MemoryMax=40G`, and `OOMPolicy=continue`. The persistent Nix store remains an
isolated alternate store rooted at `/srv/apps/openchamber/nix-root`; the
application user cannot control the host Nix store.

## Verification

- Parse every hardened JavaScript file and exercise the OpenChamber CLI,
  OpenCode CLI, server lifecycle, and scheduled-task pause/resume behavior.
- Test updater promotion, activity deferral, missing-OpenCode recovery,
  rollback, interrupted-transaction recovery, and health-restart state paths.
- Test host image identity, exact-image rollback, durable rollback state,
  systemd override behavior, and failed-replacement recovery.
- Evaluate generated container scripts and run shell syntax and formatting
  checks.
- Before live deployment, build on the target `aarch64` host. Apply only after
  OpenChamber reports idle; then verify systemd units, process environment,
  versions, health, restart counters, and restart audit records at runtime.
