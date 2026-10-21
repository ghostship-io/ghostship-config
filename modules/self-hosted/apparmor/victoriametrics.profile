# Container policy for the SIEM store (siem/storage.nix), written 2026-10-21
# from the image: VictoriaMetrics v1.154.1 (alpine base, unused busybox); uid/gid 3100; no capabilities; read-only image.
# /victoria-metrics-prod is a static Go binary started directly by the runtime (no init or
# shell), so the top profile is the server domain. Data lives on the noexec
# /data volume; the heartbeat opens a throwaway store in the noexec /tmp.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-victoriametrics flags=(complain,attach_disconnected,mediate_deleted) {
  # No exec transitions at all: the store never spawns helpers.
  /victoria-metrics-prod mr,

  /data/ rw,
  /data/** rwk,
  # Heartbeat store (port 18428), discarded with the exec.
  /tmp/ rw,
  /tmp/** rwk,

  /etc/{hosts,resolv.conf,nsswitch.conf,passwd,group} r,
  /dev/null rw,

  # Go runtime and the store's resource discovery: cgroup CPU and memory
  # limits, memory size, its own process statistics and open descriptors.
  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm,status,io,limits,fd/} r,
  /proc/meminfo r,
  /sys/fs/cgroup/{cpu.max,memory.max} r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
  /proc/sys/net/core/somaxconn r,

  # HTTP API on :8428 (ingestion and queries). AppArmor socket rules
  # cannot restrict ports or peers; the SIEM network blocks egress.
  network inet stream,
  network inet6 stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-victoriametrics,

  # The collector's daily heartbeat read.
  audit /proc/sys/kernel/random/boot_id r,
}
