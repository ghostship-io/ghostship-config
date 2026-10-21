# T3 privilege hardening

T3 is a trusted administration environment: its agents retain unrestricted root
SSH to Chill Penguin. Removing container privileges limits accidental damage and
development-container access; it does not isolate the host from an agent holding
those SSH credentials. The rootful production Podman socket stays outside T3.

The change is staged behind `ghostship.t3code.hardening.enable`, which defaults
to off, and behind `ghostship.t3codeDocker.enable`, which no host configuration
enables. Keep both disabled until the complete candidate passes the acceptance
below. A host switch must not replace the active T3 container or restart its
inner runtime; follow the
[session guard](container-workflow.md#preserve-the-active-t3-code-session).

## Runtime boundary

The hardened platform replaces `--privileged` with the capability list shared by
the configuration and probe in `packages/t3code/runtime-caps.json`. The list
excludes `SYS_ADMIN`, `SYS_MODULE`, `SYS_PTRACE` and `NET_ADMIN`. `SYS_RESOURCE`
supports the existing OOM guard. Container seccomp remains enabled. The
privileged-container exception in `ghostship.security.privileged_allow` is
withdrawn for the hardened profile, so the container holds no privileged
exception at all.

Root SSH to Chill Penguin remains the trusted administration path.
`ghostship.security.host_ssh_clients` keeps `t3code`, so the container stays an
expected host SSH client while container privileges shrink.

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

## Rootless engine architecture

Development Docker runs in a separate rootless engine. The T3 container never
starts a rootful daemon: under hardening, `t3code-dockerd-run` only waits for
the separate engine to answer and reports readiness.

The engine runs as a dedicated host account `t3code-docker` with UID 62040. The
module forbids that UID from being the apps UID 3000, and reserves a dedicated
65536-ID subordinate range starting at 2000000. It lives in a genuine systemd
user manager `user@62040.service` whose `RootDirectory` and
`NetworkNamespacePath` point at the engine's private rootfs and namespace. The
manager delegates the CPU, cpuset, IO, memory and PID controllers, and carries
aggregate limits of 16G memory, a 400% CPU quota and 4096 tasks. Its unit path
holds only the basic targets and its own session bus, so it cannot start
ordinary host user services. `dockerd-rootless` runs inside it with slirp4netns
networking and the builtin port driver, and the engine requires cgroup v2.

Engine configuration is fixed in `modules/self-hosted/t3code-docker.nix`: data
root under `/var/lib/t3code-docker`, fuse-overlayfs storage, the systemd cgroup
driver, `live-restore` off, local log rotation, and the address pool
172.28.0.0/16. The daemon carries the label
`ghostship.t3code-docker=candidate`, and the acceptance run refuses to mutate
any daemon that does not carry it.

The engine closure is a link farm of Docker, systemd, dbus, rootlesskit,
slirp4netns, fuse-overlayfs and their helpers. `host-candidate.py` seeds exactly
that closure into T3's private inner Nix store and refuses to assemble a rootfs
whose closure is missing from it. The host store is never mounted.

The network is host-owned. The engine runs in the `t3code-docker` namespace
behind a veth pair, and an nftables table guards it: the host drops everything
arriving on the engine's interface, drops forwarded IPv6 and forwarded traffic
to host-local, private, loopback and link-local ranges, confines egress to the
configured public interface, and masquerades the namespace address on that
interface. IPv6 is disabled inside the namespace. Denied host, production and
LAN access are acceptance observations, not claims of this document.

Two sockets reach T3. The engine's API is relayed by `systemd-socket-proxyd`
from `/run/t3code-docker/docker.sock`, group `apps` only, into the T3 container
as `/var/run/docker.sock`. The relay runs without new privileges, with a strict
system view, with `/home`, `/root` and `/srv` inaccessible, and with only Unix
sockets permitted. Published ports reach T3 through a second private Unix
socket, `/run/t3code-docker/ports.sock`, whose gateway runs inside the engine
namespace. The bridge inside T3 discovers published ports through the API and
binds them on T3's own loopback, so no new host listener appears.

## Process visibility tradeoff

The engine's manager runs with `ProtectProc=default`, not `invisible`. This is a
deliberate concession, and the concession is narrow to that one dedicated
account.

Rootless runc calls `busctl --user status` to find the user manager that owns
a cgroup, and that lookup needs `/proc/1/cgroup`. `ProtectProc=invisible` hides
that file, systemd cannot augment `OwnerUID`, and runc falls back to the rootful
system bus instead of the engine's private session bus. A transient probe that
bound `/proc/1/cgroup` read-only while `ProtectProc=invisible` was still active
could not read it either, so hiding the file is the only thing that made the
lookup fail.

Two supporting changes follow from that failure. The engine's private D-Bus
configuration now carries an explicit listen address, because a session bus
without one does not answer a `--user` status request. And systemd's tools are
on the engine's `PATH`, because runc shells out to `busctl` and the engine
closure did not provide it.

What `ProtectProc=default` gives up is process metadata. The dedicated UID 62040
manager can read host process metadata and command lines, so this document does
not claim that host processes are hidden from the engine. What still holds:

- The engine has a private rootfs with its own passwd, group and subordinate ID
  files, so it is not the host's user database.
- The engine runs under its own host UID, never as root and never as the apps
  UID 3000.
- Root-owned proc roots and other users' environments stay unreadable to that
  UID by ordinary file permissions.
- The engine has no host system bus: its session bus listens on its own private
  path, and the host's bus is not mounted into the engine rootfs.
- The network namespace, the nftables filter and the delegated cgroup limits are
  unchanged by this setting.

Apply the relaxation only to the dedicated UID 62040 manager. A container that
carries `ProtectProc=invisible` keeps it.

## Engine filesystem

The engine's rootfs is a private tmpfs assembled by
`packages/t3code/docker-sandbox/rootfs.py`, plus an empty tmpfs on its `/run`.
`ProtectProc` implies `MountAPIVFS`, which would otherwise overlay that `/run`
with a fresh tmpfs and hide the engine's own runtime sockets. The engine
exposes three writable project trees and nothing else from the host's data:

- `/workspace`, the T3 workspace.
- `/home/t3code/.t3/worktrees`, the T3 worktrees.
- `/tmp`, the shared T3 temporary directory.

The Nix store is mounted read-only from T3's private inner store, and the Nix
daemon socket inside it is masked, so a read-only bind does not become a path to
the inner daemon. The engine receives no T3 home contents beyond that worktrees
subtree, no home credentials, no provider secrets and no secret projections. The
remaining mounts are the engine's own state and runtime directories, cgroup and
proc, the character devices it needs, and the capability-limited `newuidmap` and
`newgidmap` helpers.

## Bind ownership mapping

The engine's bind mounts carry an ID map, so the owners of the files it writes
are usable by T3. On the mounted paths, a container running as UID 0 writes as
host UID 3000, the T3 workspace owner, and a container running as UID n (n ≥ 1)
writes as host UID 2000000 + n − 1, the subordinate ID that the container UID
maps to. Files owned by the T3 workspace owner appear inside the engine under
the engine's own UID, so container-root writes land on the host as UID 3000
without any chown and without the engine joining the production apps group. The
map also gives filesystem UID 0 its own identity, which keeps a root-owned
directory such as T3's mode 1777 temporary directory usable by the engine
process. That entry grants the engine no root identity: the engine process
stays UID 62040.

## Explicit project permissions

Rootless images that run as a non-root user still need to write into a project.
Those grants are explicit and owner-applied. The project owner, T3 UID 3000,
runs `setfacl` on the one output or project directory they choose to share.
Nothing else grants access: the engine performs no recursive ownership change,
and no existing project has its ownership or permissions rewritten.
`packages/t3code/docker-sandbox/acceptance.py` applies its grant to a
disposable fixture only, and `idmap-probe.py` states that no ownership change
or broad permission is applied to real data.

A narrow grant for one container UID, run by the directory owner, looks like
this. The host UID is the subordinate ID that the container UID maps to:

```sh
# 2000999 = subIdStart 2000000 + container UID 1000 - 1
setfacl -m u:2000999:rwx,d:u:3000:rwx,d:u:2000999:rwx \
  /srv/ghostship/workspace/<project>/output
```

The access entry gives that one container UID write access to the directory
itself. The default entries apply to newly created children: `d:u:3000` keeps
T3 able to edit and delete what the container creates, and `d:u:2000999` keeps
the container's own access to new files. Default entries reach only new
children; they do not change existing files, and a file created with an
explicit mode keeps that mode.

Two limits decide whether a grant works in practice. Every ancestor directory
of the granted path must grant search permission to the mapped host UID, since
an ACL on the final directory cannot open the path above it; a project
directory that only its owner may enter stays closed to the container no matter
what the granted directory allows. And an explicit mode of 0600 on a created
file, or any later `chmod`, recomputes the ACL mask and can leave the inherited
named-user entries present but without effective permission. Verify the
effective rights with `getfacl`, not with the entry names alone.

## Recorded results

The hardened image built, and the platform probe passed against the actual
candidate c83de303: the effective capability set matched
`packages/t3code/runtime-caps.json` exactly, `SYS_ADMIN` was absent, seccomp
was filtering, and systemd, a Nix daemon build, a Bubblewrap sandbox and
cross-user OOM protection all worked. The active T3 container, its start time
and its service PIDs were unchanged afterwards. The probe never claims
authenticated provider acceptance.

The rootless engine's user manager failed on first start. The dedicated empty
`/run` mount in commit 5296b4bd fixed that boot while preserving `ProtectProc`.
The daemon then failed on `/tmp` permissions. The Btrfs ID-map probe was
extended with a root-owned mode 1777 case, which failed, and commit 447e4f67
turned it green by mapping filesystem UID 0 to itself.

The engine's bus and cgroup lookup failed next. Commit de08169c put systemd's
tools on the engine `PATH`, and commit 9660ad25 gave the private session bus an
explicit listen address. The `ProtectProc=invisible` setting was then found to
hide `/proc/1/cgroup` and make runc fall back to the rootful system bus, so the
dedicated UID 62040 manager now runs with `ProtectProc=default`. That
relaxation is under test on the dedicated account only.

Live Docker workflows have not passed. The candidate engine has not completed
the acceptance run below, so no live Docker acceptance is claimed and the
hardening options stay disabled.

## Candidate acceptance

Run only committed artifacts on the host. Build the image through the explicitly
hardened candidate configuration; the ordinary legacy configuration does not
expose a candidate image. Load its distinct
`localhost/ghostship-t3code-candidate:hardening` tag without changing the
production image tag. The platform probe uses fresh disposable home/workspace
state, no credentials and no network:

```sh
nix build --impure --file tests/t3code-hardening-candidate.nix
podman load -i result
python3 packages/t3code/hardening-probe.py --image localhost/ghostship-t3code-candidate:hardening
```

Load the committed `ghostship-t3code` profile in complain mode first. The probe
starts a dedicated target instead of production application services, and checks
systemd, a user service, the Nix daemon, a fresh build, Bubblewrap, OOM
protection, the attached profile, capability equality and enabled seccomp. It
removes its own candidate and compares the active container ID, start time,
container PID, service PID and inner T3 service PID before and after. An
existing candidate is left for inspection rather than adopted. A platform pass
alone does not permit cutover.

Stage the rootless engine candidate as host root. The driver accepts only the
dedicated UID 62040 account, refuses to adopt an existing manager or unit, and
records ownership before starting anything:

```sh
nix build --impure --file tests/t3code-docker-candidate.nix
python3 packages/t3code/docker-sandbox/host-candidate.py start result
```

Confirm the ownership mapping on the target kernel. This probe creates no
accounts, touches no project or T3 state, and checks the mapped owner, the
container-root write, the root-owned temporary directory and the explicit ACL
case:

```sh
python3 packages/t3code/docker-sandbox/idmap-probe.py
```

Record the live canaries the engine must not reach, from a permitted control
namespace. The report must be fresh, within 300 seconds of the acceptance run,
and must list every denied endpoint:

```sh
python3 packages/t3code/docker-sandbox/canary-probe.py \
  --endpoint 192.168.0.10:22 --endpoint 10.89.7.2:8080 \
  --output /tmp/t3code-canaries.json
```

Run the Docker workflows through the platform probe. The workspace must be an
absolute, real directory owned by T3 UID 3000. The probe mounts the private API
and ports sockets into the fresh-home candidate and runs the acceptance script
as UID 3000:

```sh
python3 packages/t3code/hardening-probe.py \
  --image localhost/ghostship-t3code-candidate:hardening \
  --docker-workspace /srv/ghostship/workspace/<project> \
  --docker-control-report /tmp/t3code-canaries.json \
  --denied-endpoint 192.168.0.10:22 --denied-endpoint 10.89.7.2:8080
```

The acceptance script refuses a daemon without the candidate label, and refuses
to run as any UID other than the T3 workspace owner. It checks rootless
operation with the systemd cgroup driver on cgroup v2, an image build with
public DNS, bind writes as container UID 0, 3000 and 1000 with the expected
host owner and with T3 editing and deleting the result afterwards, per-container
memory and PID limits, outbound HTTPS, interactive TTY allocation, refusal of
the recorded private and local canaries even with host networking and
privileges, a Compose project on its own isolated network reached through the
T3 localhost bridge on a dynamically allocated port, service-to-service DNS
inside that network, the service name not resolving outside it, and named volume
content surviving container recreation. Every object it creates carries a
unique label, so its cleanup removes only its own objects.

Stop the staged engine when the run ends. The driver keeps the dedicated
account and the Docker data for inspection and removes only the units it
installed:

```sh
python3 packages/t3code/docker-sandbox/host-candidate.py stop result
```

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

## Current compatibility limits

The port path forwards TCP only. A UDP publication is neither discovered nor
relayed, because the bridge collects published ports of type TCP only. The
engine namespace has IPv6 disabled and its nftables rules drop IPv6, so an IPv6
publication does not reach T3. The gateway accepts only ports of 1024 or
above, so a low published port is refused. The bridge discovers only ports
published on all interfaces or on loopback, so a port published to one specific
address is not forwarded through the T3 bridge. These are limits of the current
implementation, not configuration choices.
