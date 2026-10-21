# Container policy for the SIEM UI (siem/ui.nix), written 2026-10-21 from the image:
# Grafana 13.2.4 distroless; uid/gid 472; no capabilities; read-only image;
# no_new_privs, so the profile is flat (child transitions never happen).
# Grafana runs the vendored VictoriaLogs plugin backend from the read-only
# store mount; nothing else executes. No abstractions or explicit denies:
# unmatched operations stay allowed and visible while in complain mode.
profile ghostship-grafana flags=(complain,attach_disconnected,mediate_deleted) {
  /usr/share/grafana/bin/grafana mr,
  /usr/share/grafana/ r,
  /usr/share/grafana/** r,
  # The VictoriaLogs datasource backend (go-plugin), vendored and pinned.
  /var/lib/grafana-plugins/ r,
  /var/lib/grafana-plugins/** r,
  /var/lib/grafana-plugins/victoriametrics-logs-datasource/victoriametrics_logs_backend_plugin_linux_arm64 rix,

  # SQLite state and sessions on the noexec data volume.
  /var/lib/grafana/ rw,
  /var/lib/grafana/** rwk,
  /etc/grafana/ r,
  /etc/grafana/** r,
  /run/secrets/vmauth-password r,
  /tmp/ rw,
  /tmp/** rwk,

  /etc/{hosts,resolv.conf,nsswitch.conf,passwd,group,localtime,mime.types} r,
  /etc/ssl/certs/ r,
  /etc/ssl/certs/** r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/urandom r,

  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm,status,limits,fd/,cmdline} r,
  /proc/meminfo r,
  /proc/sys/net/core/somaxconn r,
  /sys/fs/cgroup/{cpu.max,memory.max} r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,

  # HTTP on :3000 for cloudflared; vmauth and aardvark-dns on the UI network;
  # the plugin's go-plugin channel to its child.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  network unix stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-grafana,

  # The collector's heartbeat: a static read-only helper (siem/heartbeat.c).
  /opt/ghostship-heartbeat/read-file rix,
  audit /proc/sys/kernel/random/boot_id r,
}
