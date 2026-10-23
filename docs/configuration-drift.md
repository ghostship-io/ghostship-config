# Configuration drift

The deployment host no longer upgrades itself. Unattended upgrades ran outside
change control, so a host could move to a revision nobody reviewed and nobody
recorded. The replacement is a daily, read-only check that names the drift
instead of acting on it.

## What runs

`ghostship-configuration-drift.timer` runs
`ghostship-configuration-drift.service` once a day, persistently, with a
random delay. The service runs `modules/self-hosted/configuration-drift.py`
as a oneshot. It never builds, switches, sets the system profile, activates a
generation, stops a timer or restarts a service.

The host sets `myOptions.autoUpgrade.enable = false`; the shared module then
renders no `nixos-upgrade` service or timer. The two WSL hosts keep their
unattended upgrade.

## The two checks

**Generation.** The running system link (`/run/current-system`) and the system
profile (`/nix/var/nix/profiles/system`) must name the same store path. When
they differ, a reboot would revert the activation, so the service publishes a
security alert immediately, whatever the revision age.

**Revision.** The running revision is read from the running system:

```
/run/current-system/sw/bin/nixos-version --configuration-revision
```

The module records that value from `system.configurationRevision = self.rev`,
so it describes the build that is actually running, not the checkout or the
candidate being evaluated. The check fetches the source branch into its own
private bare cache and compares the running revision with main:

- the running revision is main: no alert, and any old observation is cleared;
- main is an ancestor of the running revision: the host is ahead, no alert;
- the running revision is an ancestor of main: the host is behind;
- neither is an ancestor of the other: diverged or unrelated histories are an
  explicit error, never "behind" and never health.

A behind host is reported once `now - first_observed_behind > 86400` seconds
for that same running revision. At exactly 86400 seconds there is no alert; at
86401 there is. When main advances, the first observation is kept, so the
clock does not restart just because the gap grew. Convergence clears the
observation, and a new running revision starts a fresh one.

A missing or dirty `configurationRevision` is unknown, never healthy. So is a
failed fetch, a running revision that is not in the fetched history, or a
missing symlink. Each returns nonzero with the reason on stderr. A failed
notification also returns nonzero, so the next execution retries it.

## Notifications

Both alerts go through `config.ghostship.notify.package` on the `security`
topic at priority 4, with a stable dedupe key per kind. No `--incident` flag is
passed: the check reports, and a human decides whether to act.

The ntfy address is read from the root-owned, world-readable container snapshot
at `/run/ghostship-podman/containers.json`, the same source the SIEM alert
bridge uses. The check takes the `ntfy` address on `ghostship_net` and port
8080, rejects a snapshot older than 300 seconds, and passes the resulting URL
to the notifier as `GHOSTSHIP_NOTIFY_URL`. It never calls the Podman API: a
hardened unit must not open the container storage, and nothing here may create
containers. A missing, stale or incomplete snapshot is an explicit nonzero
error, so the next run retries instead of silently losing the alert.

## State and confinement

The service's only writable host path is
`/var/lib/ghostship-configuration-drift` (`StateDirectory`, mode 0700, UMask
0077):

- `state.json`: the running revision, the first observation and the main tip;
- `repository.git`: a bare fetch cache, never a deployment checkout;
- `notify/`: the notifier's own dedupe state, kept inside the same directory.

The host links and the system profile are read-only. The unit runs with
`ProtectSystem=strict`, `ProtectHome=true`, a private `/tmp`, no capabilities
and no new privileges. It starts after the container snapshot job and reads
that snapshot read-only. The source is the same public HTTPS repository as
`modules/common/automation.nix`, so no new credential is needed.

## Responding to an alert

Update the host through change control: review the change, activate it with
the normal deploy procedure, and verify that the generation links match. Do not
turn unattended upgrades back on to silence the alert, and do not delete the
state file: the alert returning is the point.

## Checks

```
python3 -m unittest discover -s tests -p test_configuration_drift.py
nix eval --impure --json --file tests/configuration-drift.nix
```

The Python tests drive the real command against temporary Git remotes and a
fake running system. They pin the 86400/86401 boundary, retention when main
advances, convergence, a new running revision, running ahead, generation
drift, every explicit failure, delivery retry, and a command guard that proves
no build, switch or service command is run.
