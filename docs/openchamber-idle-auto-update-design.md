# OpenChamber Idle Auto-Update Design

## Goal

Allow OpenChamber and OpenCode updates to download in the background without
restarting `openchamber-web.service` while OpenChamber reports active work.

## Selected Design

Keep the existing four-hour updater responsible for installing the latest
tools and comparing their versions before and after maintenance. When either
version changes, write a queued pending-restart marker instead of
restarting the web service immediately.

Add a separate one-minute systemd timer that handles only pending restarts. It
must:

1. Exit without action when no pending-restart marker exists.
2. Require `openchamber-web.service` to be active.
3. Query OpenChamber's `GET http://127.0.0.1:3000/api/session-activity`
   endpoint.
4. Treat the runtime as idle only when the response is a JSON object and every
   reported session has `type = "idle"`. An empty object is idle.
5. Defer the restart when OpenChamber reports `busy`, `cooldown`, or any
   unknown state, or when the request or JSON validation fails.
6. Query OpenChamber again immediately before restarting, then restart only if
   the second response is also idle.
7. Remove the pending marker only after a successful restart.

OpenChamber is the activity authority. The restart gate must not discover the
managed OpenCode port, read its generated password, or interpret OpenCode
session state directly.

The existing web monitor uses the same idle check before restarting an active
but unhealthy web service. If the activity endpoint is unavailable, the
monitor defers because it cannot prove that work is complete. It may still
start `openchamber-web.service` when that service is already stopped, because
there is no running work left for that start to interrupt.

The Podman health command follows the same rule. A healthy root endpoint
passes. If the web service is active but the root endpoint is unhealthy, the
container remains healthy for supervision purposes until OpenChamber reports
all activity idle; active or unknown activity cannot trigger
`--health-on-failure=kill`. An inactive web service still fails the container
health check because there is no running work for a recovery to interrupt.
Container setup and web activation are treated as healthy while they are still
activating during the container system manager's startup grace period. The
background bootstrap may also use that grace while the web service starts
independently. This keeps a long first-start tooling build from being killed
and restarted in a loop. That exception and the unit start timeouts are bounded
at 20 minutes so a genuine deadlock remains recoverable.

On normal container starts, minimal setup reuses the persisted OpenChamber and
OpenCode binaries and starts the web service without waiting for project
hooks. Bootstrap and before-web hook sets then run in the background. Their
completion writes the same root-owned pending marker used by tool updates, so
the restart gate applies their changes only after OpenChamber reports every
session idle. First-ever startup still installs missing tool binaries before
the web service starts.

Persist `/nix` in an isolated alternate store rooted at
`/srv/apps/openchamber/nix-root`, not by bind-mounting the host's primary Nix
store. The host seeds the image content closures into that store with
`nix copy` before container creation and refreshes image GC roots. Inside the
container, a root-owned `nix-daemon` owns the store database and accepts builds
from the allowed `openchamber` user. This retains container-built closures
across image changes while preventing the application user from controlling a
store database later consumed by host root.

Keep memory-intensive child work in the web service cgroup. Set
`MemoryHigh=32G`, `MemoryMax=40G`, and `OOMPolicy=continue` so the cgroup is
throttled before it threatens the 62 GiB host and a cgroup OOM does not turn
one failed child process into a full OpenChamber service stop.

## Alternatives Considered

- Use OpenChamber's proxied `/api/session/status`: rejected because the
  upstream status endpoint is directory-scoped and does not represent every
  project known to OpenChamber.
- Inspect the managed OpenCode process and API directly: rejected because it
  duplicates OpenChamber's own aggregate state and depends on private child
  process details.
- Keep the updater service running until the runtime becomes idle: rejected
  because a long-running update job is harder to supervise and does not retain
  a clean queued-restart boundary.

## State and Failure Handling

Store the pending marker and updater lock under the root-owned
`/run/openchamber-tool-update/` directory. They survive timer invocations but
remain runtime state, and the unprivileged application cannot redirect root
file operations through symlinks. The marker records the installed
OpenChamber and OpenCode versions for diagnostic logging. Any normal web
service start clears it because that start already loads the downloaded
versions.

A failed activity probe is not evidence of idleness. It leaves the marker in
place for the next timer run. If the web service is already stopped, the gate
leaves it stopped and clears the marker because the next normal service start
will already load the downloaded versions without another restart.

## Verification

- Evaluate and build the `chill-penguin` NixOS configuration.
- Test the gate with no marker, malformed activity JSON, `busy`, `cooldown`,
  unknown, and idle responses.
- Verify the web monitor defers an active-service recovery when OpenChamber is
  busy or its activity state is unavailable.
- Verify the container health check does not request a kill while an active web
  service reports busy or unknown activity.
- Verify the web service exposes the configured memory high/max limits and
  continue-on-OOM policy.
- Deploy on `chill-penguin` and verify both timers and services are loaded.
- Verify a pending marker is retained while OpenChamber reports active work.
- Verify no restart occurs when installed versions are unchanged.
- Verify an actual queued update restarts only after OpenChamber reports idle,
  then clears the marker and returns healthy.
