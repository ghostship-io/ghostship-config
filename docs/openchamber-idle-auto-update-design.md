# OpenChamber Idle Auto-Update Design

## Goal

Allow OpenChamber and OpenCode updates to download in the background without
restarting `openchamber-web.service` while OpenChamber reports active work.

## Selected Design

Keep the existing four-hour updater responsible for installing the latest
tools and comparing their versions before and after maintenance. When either
version changes, write a persistent pending-restart marker instead of
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

Store the pending marker under
`/home/openchamber/.config/openchamber/run/` so it survives timer invocations
but remains runtime state. The marker records the installed OpenChamber and
OpenCode versions for diagnostic logging.

A failed activity probe is not evidence of idleness. It leaves the marker in
place for the next timer run. If the web service is already stopped, the gate
leaves it stopped and clears the marker because the next normal service start
will already load the downloaded versions without another restart.

## Verification

- Evaluate and build the `chill-penguin` NixOS configuration.
- Test the gate with no marker, malformed activity JSON, `busy`, `cooldown`,
  unknown, and idle responses.
- Deploy on `chill-penguin` and verify both timers and services are loaded.
- Verify a pending marker is retained while OpenChamber reports active work.
- Verify no restart occurs when installed versions are unchanged.
- Verify an actual queued update restarts only after OpenChamber reports idle,
  then clears the marker and returns healthy.
