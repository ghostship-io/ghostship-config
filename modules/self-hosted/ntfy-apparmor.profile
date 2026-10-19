# Monitor ntfy, its shell/wget health check, and the collector's /bin/cat.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-ntfy flags=(complain,attach_disconnected,mediate_deleted) {
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-ntfy,

  /usr/bin/ntfy rix,
  # BusyBox includes a shell; put every applet in a separate domain that cannot
  # read ntfy credentials or persistent state. AppArmor cannot select applets by argv.
  /bin/{busybox,cat,sh} cx -> tools,
  /usr/bin/wget cx -> tools,
  # ntfy is static; the observed BusyBox executable dynamically loads musl.
  /lib/ld-musl-aarch64.so.1 mr,

  /dev/null rw,
  /dev/{random,urandom} r,
  /etc/{hosts,resolv.conf,nsswitch.conf} r,
  /etc/ssl/cert.pem r,
  /etc/ssl/certs/ca-certificates.crt r,

  /etc/ntfy/ r,
  /etc/ntfy/** r,
  /var/lib/ntfy/ rw,
  /var/lib/ntfy/** rwk,

  # Go's cgroup CPU quota discovery; cpu.max is open in the live process.
  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo} r,
  /sys/fs/cgroup/cpu.max r,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    # Health checks and audit probes only. No ntfy config/database, temporary
    # files or arbitrary script-tree permissions; no transition back to the server.
    /bin/{busybox,cat,sh} rix,
    /usr/bin/wget rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    /etc/{hosts,resolv.conf,nsswitch.conf} r,
    audit /proc/sys/kernel/random/boot_id r,
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-ntfy,
    signal (send, receive) peer=ghostship-ntfy//tools,
  }
}
