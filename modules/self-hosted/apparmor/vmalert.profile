# Container policy shared by vmalert-logs and vmalert-metrics (siem/alerting.nix),
# written 2026-10-21 from vmalert v1.154.1 (alpine base, unused busybox);
# uid/gid 3100; no capabilities; read-only image; rules mounted read-only.
# /vmalert-prod is a static Go binary started directly by the runtime; it
# evaluates rules against the SIEM stores, writes alert state to
# VictoriaMetrics and serves its alert API. It sends no notifications.
# The registry renames this profile per instance (vmalert-logs, vmalert-metrics).
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-vmalert flags=(complain,attach_disconnected,mediate_deleted) {
  # No exec transitions at all.
  /vmalert-prod mr,

  /rules/ r,
  /rules/** r,

  # Go resolver: stores are addressed by container name.
  /etc/{hosts,resolv.conf,nsswitch.conf,passwd,group} r,
  /dev/null rw,

  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm,status,io,limits,fd/} r,
  /proc/meminfo r,
  /sys/fs/cgroup/{cpu.max,memory.max} r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
  /proc/sys/net/core/somaxconn r,

  # Store queries, state writes, DNS and the alert API on :8880.
  # The SIEM network blocks egress beyond its own containers.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-vmalert,

  # The collector's daily heartbeat read.
  audit /proc/sys/kernel/random/boot_id r,
}
