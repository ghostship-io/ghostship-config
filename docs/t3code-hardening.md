# T3 runtime hardening and development engine

The outer runtime hardening option remains off by default. The development
engine is independently a dedicated **rootless Podman** service for both outer
runtime modes. It never projects the host rootful Podman API into T3.

## Engine boundary

`modules/self-hosted/t3code-podman.nix` defines a dedicated account, subordinate
UID/GID range, real user manager, private root filesystem and host-owned network
namespace. The engine uses crun, fuse-overlayfs and systemd cgroup delegation.
A finite closure is copied into T3's private Nix store before its manager starts;
the host store and host Nix daemon socket are not mounted into the engine.
The manager has the NixOS re-exec alias inside its private filesystem, pointing
only at the seeded systemd closure, so a host switch can re-execute it. API and
port relays follow the manager's lifetime; a dead manager must not leave an apparently live gateway behind.

The engine has its own memory, CPU and task ceilings. With outer hardening on,
the engine manager and T3 container share the bounded parent slice defined in
`t3code-hardening.nix`, with supervisory PID headroom. This shared ceiling is a
combined limit; each child's maximum is not a guaranteed simultaneous budget.
With outer hardening off, that common-parent containment is not claimed.

The manager retains proc metadata visibility pending runtime acceptance of a
narrower policy. It cannot read other users' protected environments or follow
root-owned proc roots. No host system bus is projected.

The host controls the namespace and nftables boundary. It denies host services,
production containers, private/LAN destinations, IPv6 and unexpected egress
interfaces. Public DNS and public IPv4 egress remain supported. Engine-side
privilege cannot remove the host filter. Root SSH administration remains an
explicit independent authority and is not contained by this boundary.

The apps-only Unix API relay checks SO_PEERCRED on every connected upstream
socket before forwarding application bytes. A symlink to a root-owned host
socket is rejected. The systemd-owned listener is never stat'ed or unlinked by
the relay. A separate Unix gateway forwards only high TCP ports to namespace
loopback; the unprivileged T3 bridge listens only on container loopback.
UDP, IPv6, low ports and address-specific forwarding are not supported.

## Development compatibility and data

Use `podman` and `podman compose` (the podman-compose provider). No compatibility
CLI alias is installed. Builds use Containerfile; services use explicit project
networks for DNS. Rebuild images and volumes: existing engine storage is neither
imported, mounted, deleted nor migrated. No named consumer requires old data.
BuildKit/buildx, Swarm, engine plugins and live-restore have no named consumer
in this repository and are not provided or emulated.

`dockerTools` remains only as nixpkgs' image construction library: its outputs
are container image archives consumed by Podman, not an installed runtime.
Registry names, upstream image entrypoints and compatibility API field names
are upstream interfaces; they do not install a runtime backend.

Container root writes to idmapped project mounts as the T3 owner. Nonroot image
users retain subordinate ownership and require explicit project permissions.
Grant ACLs only to a chosen disposable/project directory; never recursively
change existing project ownership or make the workspace world-writable. Map
container UID n using the configured subordinate start + n - 1, grant the T3
owner access to new outputs, and verify that it can edit and delete them.
Restrictive explicit file modes can still reduce an ACL mask. Ancestor search
permissions must also allow traversal.

## Checks and enablement gates

`tests/check_podman_runtime.py` prevents runtime-package, daemon, socket,
account/group and configuration reintroduction. Unit tests exercise connected
peer credentials, refusal before bytes, inherited listener lifetime, directory
symlink safety, forwarding and candidate-manager ownership. Nix tests evaluate
actual units, ID collision refusal, resources, mounts and hardened argv admission.
Engine startup also verifies that the configured helper directories contain
executable network, published-port and init helpers; a custom path cannot silently
drop workload support.

Integration acceptance remains separate from these fast checks. No prior engine
workflow result establishes Podman compatibility. After landing and deploying the
host engine, verify
build/run, Compose DNS and isolation, named-volume recreation, bind ownership,
TTY, published high TCP, cgroup limits and network denial with disposable objects. Network denial requires a fresh positive control for each canary.
Production common-parent placement/stress proof is a separate gate.

For a disposable engine candidate, build `tests/t3code-podman-candidate.nix` and
use `packages/t3code/dev-engine/host-candidate.py`. It refuses a production spec,
active/transitional manager, preexisting unowned unit or mismatched marker.
Candidate storage is separate from production; acceptance verifies the actual
rootless native info and candidate graph root before any mutation. The candidate
cannot run beside an active production manager with the same UID. Cleanup removes
only its exact owned units and retains data for inspection.

Use `packages/t3code/hardening-probe.py --help` for disposable outer-runtime
checks and `--podman-workspace` workflow checks. Never run them against the active
T3 container. Preserve the session guard in [container workflow](container-workflow.md).

Activation changes the T3 image and requires the coordinated idle deployment
window. Source readiness, candidate tests and deployed runtime proof are distinct.
