# Fallback for containers started without their own policy: ad-hoc and job
# containers. Every declared container has a strict profile (container-apparmor.nix),
# so this grants nothing beyond runtime signals. In complain mode every other
# access is logged; the deny rules are Podman's baseline and apply even then.
# Declared under a stable name so NixOS replaces it on reload. Podman loads
# containers-default-<version> itself, and `aa-remove-unknown` on every
# AppArmor reload unloads it, leaving running containers unconfined.
include <tunables/global>

profile ghostship-container-default flags=(attach_disconnected,mediate_deleted) {
  signal (receive) peer=unconfined,
  signal (send,receive) peer=ghostship-container-default,
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
}
