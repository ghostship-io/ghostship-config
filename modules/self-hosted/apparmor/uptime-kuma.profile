# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/louislam/uptime-kuma:2 = Uptime Kuma 2.5.6, Debian 12 (bookworm,
# glibc), Node 22.22.3; uid/gid 3000:3000, no capabilities. Mount: /app/data (rw).
# Startup: /usr/bin/dumb-init -- node server/server.js (no entrypoint script).
# Configured workload: 17 http, 4 port and 32 push monitors, one ntfy
# notification, SQLite. No ping, real-browser, docker or cloudflared monitors and
# no Apprise, so /usr/bin/{ping,chromium,apprise,cloudflared,mariadb*} and
# python3 are deliberately not executable.
# Healthcheck: `sh -c "node extra/healthcheck.js"` (dash). The collector's
# heartbeat runs `/bin/cat` (GNU coreutils).
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-uptime-kuma flags=(complain,attach_disconnected,mediate_deleted) {
  # dumb-init (PID 1) and the healthcheck's dash both start here. AppArmor
  # cannot tell their node execs apart, so the healthcheck's node also runs
  # in the server domain (it only reads extra/healthcheck.js and probes :3001).
  /usr/bin/dumb-init mr,
  /usr/bin/dash mr,
  /usr/bin/cat mr,
  /usr/local/bin/node cx -> server,
  /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 mr,
  /usr/lib/aarch64-linux-gnu/libc.so.6 mr,
  /etc/ld.so.cache r,

  /dev/null rw,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-uptime-kuma,
  # dumb-init forwards termination signals to its child.
  signal (send) peer=ghostship-uptime-kuma//server,

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/local/bin/node mr,
    /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 mr,
    /usr/lib/aarch64-linux-gnu/lib{c.so.6,dl.so.2,m.so.6,pthread.so.0,gcc_s.so.1,stdc++.so.6.0.30} mr,
    /etc/ld.so.cache r,
    # The only native addon in use; oracledb and others stay unmapped.
    /app/node_modules/@louislam/sqlite3/lib/binding/napi-v6-linux-arm64/node_sqlite3.node mr,

    # Application code is read-only; no execution of anything.
    /app/ r,
    /app/package.json r,
    /app/{server,src,db,dist,node_modules}/ r,
    /app/{server,src,db,dist,node_modules}/** r,
    /app/extra/ r,
    /app/extra/{healthcheck.js,rdap-dns.json} r,

    # SQLite database with WAL/shm and locks, db-config.json, error log,
    # uploads and screenshots.
    /app/data/ r,
    /app/data/** rwk,

    /etc/{hosts,resolv.conf,nsswitch.conf,host.conf,gai.conf,localtime} r,
    # TZ=Pacific/Honolulu.
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /proc/{stat,meminfo} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq r,
    owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,

    # TCP: the :3001 listener (push monitors, UI), http/port monitors and ntfy;
    # UDP for DNS. No raw/ICMP sockets: there are no ping monitors.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-uptime-kuma,
    signal (send, receive) peer=ghostship-uptime-kuma//server,
  }
}
