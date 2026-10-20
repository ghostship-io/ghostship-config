# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# ghcr.io/gethomepage/homepage:latest = homepage 2.6.0 (Next.js standalone),
# Alpine 3.24.2 (musl), Node 22.23.3, BusyBox; uid/gid 3000:3000, no capabilities.
# Mounts: /app/config (rw), /run/homepage-podman-broker (ro, podman API socket),
# /sys/class/net and /sys/devices/platform (ro, resources widget).
# Startup: docker-entrypoint.sh (BusyBox sh) runs `date`, `id -u` and, because
# HOSTNAME is "::", a `node -e` IPv6 bind probe; PUID is unset, so it skips
# every chown/mkdir branch and execs `node server.js`.
# Healthcheck: `sh -c "wget ... http://127.0.0.1:3000/"`. The collector's
# heartbeat runs `/bin/cat`. Both are BusyBox applets.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-homepage flags=(complain,attach_disconnected,mediate_deleted) {
  # Entrypoint shell only: no config, socket or network access here.
  /usr/local/bin/docker-entrypoint.sh r,
  # The entrypoint and healthcheck shell is BusyBox; every applet it execs
  # (date, id, wget) is the same binary and moves to the tools domain.
  /bin/busybox mr,
  /bin/busybox cx -> tools,
  /usr/local/bin/node cx -> server,
  /lib/ld-musl-aarch64.so.1 mr,

  /dev/null rw,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-homepage,
  signal (send) peer=ghostship-homepage//{server,tools},

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # Node and its exact libraries; the image has no other native addons in use.
    /usr/local/bin/node mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/libgcc_s.so.1 mr,
    /usr/lib/libstdc++.so.6.0.34 mr,
    # systeminformation shells out (`cat`, `grep`, `df`) for the resources
    # widget. Those run in a separate domain without config or socket access.
    /bin/busybox px -> ghostship-homepage//sysinfo,

    # Application code is read-only; no execution or executable mappings.
    /app/ r,
    /app/{server.js,package.json,next-i18next.config.js} r,
    /app/{.next,node_modules,public,src}/ r,
    /app/{.next,node_modules,public,src}/** r,

    # Configuration (contains service API keys) and the winston log. The app
    # copies missing skeleton files into place, so the YAML/CSS/JS are writable.
    /app/config/ r,
    /app/config/*.{yaml,css,js} rw,
    /app/config/logs/ rw,
    /app/config/logs/homepage*.log rw,

    # Docker integration through the podman API broker socket.
    /run/homepage-podman-broker/ r,
    /run/homepage-podman-broker/podman.sock rw,

    /etc/{hosts,resolv.conf,nsswitch.conf} r,
    /etc/{localtime,os-release} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,

    # libuv/V8: CPU and memory accounting (os.cpus, os.freemem, cgroup limits).
    /proc/{stat,meminfo} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq r,
    owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,

    # TCP: the :3000 listener, service widgets and openmeteo; UDP for DNS.
    # unix stream: the podman socket and libuv's socketpair stdio for helpers.
    # netlink raw: os.networkInterfaces() when Next.js logs its network URL.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    network netlink raw,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-homepage,
    signal (send, receive) peer=ghostship-homepage//server,
    signal (send) peer=ghostship-homepage//sysinfo,
  }

  # systeminformation helpers for the configured widget (cpu, memory,
  # disk "/", network "end0"): `cat /proc/stat | grep cpu`, `cat /proc/mounts`,
  # `df -kPTx squashfs` and `cat /sys/class/net/end0/...`.
  profile sysinfo flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    /proc/stat r,
    owner /proc/[0-9]*/mounts r,
    # /sys/class/net/end0 resolves into the read-only /sys/devices/platform mount.
    /sys/devices/platform/**/net/end0/operstate r,
    /sys/devices/platform/**/net/end0/statistics/{rx,tx}_{bytes,dropped,errors} r,
    # Inherited libuv socketpair stdio from the server.
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-homepage//server,
    signal (send, receive) peer=ghostship-homepage//sysinfo,
  }

  # Entrypoint applets and the healthcheck's wget. No config, socket or
  # application access; no transition back to the server.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    /etc/{hosts,resolv.conf,nsswitch.conf,localtime} r,
    audit /proc/sys/kernel/random/boot_id r,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-homepage,
    signal (send, receive) peer=ghostship-homepage//tools,
  }
}
