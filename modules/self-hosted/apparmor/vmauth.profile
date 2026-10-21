# Container policy for the SIEM read-only query proxy (siem/ui.nix), written
# 2026-10-21 from the image: vmauth v1.154.1 (static Go); uid/gid 3101; no
# capabilities; read-only image; no_new_privs, so flat. It only proxies the
# allowed read paths to the stores and spawns nothing.
profile ghostship-vmauth flags=(complain,attach_disconnected,mediate_deleted) {
  /vmauth-prod mr,
  /etc/vmauth.yml r,

  /etc/{hosts,resolv.conf,nsswitch.conf,passwd,group} r,
  /dev/null rw,
  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm,status,io,limits,fd/} r,
  /proc/meminfo r,
  /proc/sys/net/core/somaxconn r,
  /sys/fs/cgroup/{cpu.max,memory.max} r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,

  # :8427 for Grafana; the stores and aardvark-dns. The UI and SIEM networks
  # block everything else.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-vmauth,

  # The collector's heartbeat: vmauth parses the boot ID as its config and exits.
  audit /proc/sys/kernel/random/boot_id r,
}
