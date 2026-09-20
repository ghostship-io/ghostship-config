# Synara coding container

Synara is an independent T3 Code workstation at
`https://synara.ghostship.io`. It uses the same immutable image and internal
systemd services as the primary T3 Code container, but its mutable state lives
under `/srv/apps/synara` and is never shared with the running T3 Code instance.

## Initial migration

The first `podman-synara.service` start snapshots the live `/srv` Btrfs
subvolume and
reflink-copies these T3 Code paths into a staging directory:

- `/srv/apps/t3code/home`, including provider configuration, transferable
  login state, conversations, local worktrees, user services, skills, and SSH
  configuration
- `/srv/apps/t3code/workspace`, including every project and its uncommitted Git
  state
- `/srv/apps/t3code/docker`, preserving nested Docker state

The snapshot captures SQLite databases and their WAL files at one filesystem
instant. T3 Code keeps running throughout; the migration neither stops nor
restarts it. Synara atomically adopts the staged copy only after required state
and the `nixos-config` repository validate. A completion marker prevents later
starts from overwriting Synara changes. Interrupted attempts discard only the
Synara staging paths and converge by taking a fresh snapshot.

Synara receives a fresh isolated Nix store seeded from the image. Its bootstrap
hooks rebuild dynamic Ghostship tooling against that store. Provider sessions
whose upstream service permits reuse are copied; device-bound or expired
sessions may still require sign-in from a Synara terminal.

## Deployment and verification

Deploy through the committed `chill-penguin` configuration. The host switch
does not restart T3 Code because both coding-container units disable
change-triggered restarts. The first Synara start can take several minutes while
it copies directory metadata and seeds the Nix store.

Verify the live service and the migration boundary:

```sh
systemctl is-active podman-t3code.service podman-synara.service
podman inspect synara --format '{{.State.Status}} {{.State.Health.Status}}'
podman exec synara curl -fsS http://127.0.0.1:3773/ >/dev/null
podman exec --user 3000:3000 synara t3 --version
podman exec --user 3000:3000 synara codex login status
podman exec --user 3000:3000 synara gh auth status
podman exec --user 3000:3000 synara docker info >/dev/null
podman exec --user 3000:3000 synara nix store ping --store daemon
find /srv/apps/synara/workspace -mindepth 2 -maxdepth 2 -type d -name .git
```

Open `https://synara.ghostship.io` through Cloudflare Access and run a small
task with each required provider. Files created after the initial snapshot are
independent: changes in one container do not propagate to the other.

Backups include Synara's home and workspace. They exclude its reproducible
nested Docker and Nix stores, matching the T3 Code policy.
