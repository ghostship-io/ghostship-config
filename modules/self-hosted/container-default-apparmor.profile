# Podman's default container profile (containers/common template), declared
# under a stable name so NixOS replaces it on reload. Podman loads
# containers-default-<version> itself, and `aa-remove-unknown` on every
# AppArmor reload unloads it, leaving running containers unconfined.
include <tunables/global>

profile ghostship-container-default flags=(attach_disconnected,mediate_deleted) {
  include <abstractions/base>

  network,
  capability,
  file,
  umount,

  # Allow signals from privileged profiles and from within the same profile.
  signal (receive) peer=unconfined,
  signal (send,receive) peer=ghostship-container-default,
  # Allow certain signals from OCI runtimes (podman, runc and crun).
  signal (receive) peer={/usr/bin/,/usr/sbin/,}runc,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}crun*,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}podman,

  deny @{PROC}/* w,
  deny @{PROC}/{[^1-9],[^1-9][^0-9],[^1-9s][^0-9y][^0-9s],[^1-9][^0-9][^0-9][^0-9]*}/** w,
  deny @{PROC}/sys/[^k]** w,
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/kcore rwklx,

  deny mount,

  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/fs/cg[^r]*/** wklx,
  deny /sys/firmware/** rwklx,
  deny /sys/kernel/security/** rwklx,

  # Suppress ptrace denials when using 'ps' inside a container.
  ptrace (trace,read) peer=ghostship-container-default,
}
