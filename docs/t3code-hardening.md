# T3 privilege hardening

T3 is a trusted administration environment: its agents retain unrestricted root
SSH to Chill Penguin. Removing container privileges limits accidental damage and
development-container access; it does not isolate the host from an agent holding
those SSH credentials. The rootful production Podman socket stays outside T3.

The change is staged behind `ghostship.t3code.hardening.enable`. Keep it disabled
until the complete candidate passes the acceptance below. A host switch must not
replace the active T3 container or restart its inner runtime; follow the
[session guard](container-workflow.md#preserve-the-active-t3-code-session).

## Runtime boundary

The hardened platform replaces `--privileged` with the capability list shared by
the configuration and probe in `packages/t3code/runtime-caps.json`. The list
excludes `SYS_ADMIN`, `SYS_MODULE`, `SYS_PTRACE` and `NET_ADMIN`. `SYS_RESOURCE`
supports the existing OOM guard. Container seccomp remains enabled.

Nested provider sandboxes need private procfs. Unmasking `/proc/*` fixes the
kernel's locked-mount restriction; the separate T3 AppArmor learning policy and
Podman's other mount/device restrictions remain attached. AppArmor is in complain
mode, so missing permissions are evidence to review, not an enforcement claim.

Nix retains its existing `sandbox = false` configuration. The acceptance probe
checks a real daemon build as a build user and a separate Bubblewrap sandbox;
neither proves Nix sandboxed builds work.

Home, workspaces and the independent Nix store remain persistent. The broad NAS
mount is replaced by the explicit `sharedMounts` configuration. Local ROM scans
retain a read-only library; staging and downloads retain their required writable
directories. Other filesystem administration remains available over root SSH.

## Candidate acceptance

Run only committed artifacts on the host. Build the image through the explicitly
hardened candidate configuration; the ordinary legacy configuration does not
expose a candidate image. Load its distinct `localhost/ghostship-t3code-candidate:hardening`
tag without changing the production image tag. The platform probe uses fresh
disposable home/workspace state, no credentials and no network:

```sh
nix build --impure --file tests/t3code-hardening-candidate.nix
podman load -i result
python3 packages/t3code/hardening-probe.py --image localhost/ghostship-t3code-candidate:hardening
```

Load the committed `ghostship-t3code` profile in complain mode first. The probe
starts a dedicated target instead of production application services, and checks
systemd, a user service, the Nix daemon, a fresh build, Bubblewrap, OOM protection,
the attached profile, capability equality and enabled seccomp. It removes its own
candidate and compares the active container ID, start time, container PID, service
PID and inner T3 service PID before and after. An existing candidate is left for
inspection rather than adopted. A platform pass alone does not permit cutover.

Before enabling the complete runtime, also record observed results for:

- Docker build/run and Compose build/up/down, service DNS, named volumes and
  persistent data across engine restart.
- Bind sources under `/workspace`, home-based T3 worktrees, `/tmp` and the private
  Nix store, including symlink resolution and correct file ownership afterward.
- Published development ports and existing preview/tunnel workflows, including
  dynamically allocated ports, with no new public host listener.
- Engine UID mappings, memory/CPU/PID limits and denied host, production and LAN
  access; the Docker API must not be a route around those boundaries.
- T3 HTTP/WebSocket sessions, provider turns and tool sandboxes, delegated work,
  schedules, authentication persistence and recovery after candidate replacement.
- Root SSH administration, Agent Desktop access, packaged service clients and
  the scoped NAS workflows.

Use isolated candidate state for authenticated acceptance; credential values stay
inside the consuming process. Preserve the previous image and persistent state
for rollback. Queue the final replacement through the existing idle deployment
guard only after every required check passes and the reviewed change is merged.
