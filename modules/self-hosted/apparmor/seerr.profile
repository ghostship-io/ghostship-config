# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# ghcr.io/seerr-team/seerr:latest = Seerr 3.5.0 (Next.js 16 custom server),
# Alpine 3.23.5 (musl), Node 22.23.2, npm 10.9.8, BusyBox; uid/gid 3000:3000,
# no capabilities. Mount: /app/config (rw). HOME=/app (not writable).
# Startup: docker-entrypoint.sh (BusyBox sh) execs `npm start`; npm-cli.js
# (`#!/usr/bin/env node`) runs `sh -c "NODE_ENV=production node dist/index.js"`,
# and that shell execs the server, which stays a child of npm.
# Healthcheck: `sh -c "wget -q -O /dev/null ... :5055/api/v1/status"`. The
# collector's heartbeat runs `/bin/cat`. Both are BusyBox applets.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-seerr flags=(complain,attach_disconnected,mediate_deleted) {
  # Entrypoint shell only: no config or network access here.
  /usr/local/bin/docker-entrypoint.sh r,
  /bin/busybox mr,
  # Healthcheck wget and any other applet run in the tools domain.
  /bin/busybox cx -> tools,
  # npm is a Node script: it gets its own interpreter domain.
  /usr/local/lib/node_modules/npm/bin/npm-cli.js cx -> npm,
  /lib/ld-musl-aarch64.so.1 mr,

  /dev/null rw,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-seerr,
  signal (send) peer=ghostship-seerr//{npm,launch,server,tools},

  # npm only runs the package "start" script. No access to Seerr state.
  profile npm flags=(complain,attach_disconnected,mediate_deleted) {
    # The shebang interpreter (/usr/bin/env, BusyBox) is mapped here; env
    # then execs node, which stays in this domain to run npm-cli.js.
    /usr/local/lib/node_modules/npm/bin/npm-cli.js r,
    /bin/busybox mr,
    /usr/local/bin/node rix,
    # run-script's `sh -c`: a separate launcher domain, never the server.
    /bin/busybox px -> ghostship-seerr//launch,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/libgcc_s.so.1 mr,
    /usr/lib/libstdc++.so.6.0.34 mr,

    /usr/local/lib/node_modules/npm/ r,
    /usr/local/lib/node_modules/npm/** r,
    /usr/local/etc/npmrc r,
    /app/ r,
    /app/{package.json,.npmrc} r,
    # npm enables Node's compile cache (V8 code cache) under /tmp. The cache
    # is data loaded as compiled code; it is limited to this domain.
    /tmp/ r,
    /tmp/node-compile-cache/ rw,
    /tmp/node-compile-cache/** rw,

    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,localtime} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /proc/{stat,meminfo} r,
    owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,
    # libuv socketpair stdio for the spawned script.
    network unix stream,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-seerr,
    signal (send, receive) peer=ghostship-seerr//npm,
    signal (send) peer=ghostship-seerr//{launch,server},
  }

  # The `sh -c` from npm's run-script: execs only the server.
  profile launch flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox mr,
    /usr/local/bin/node px -> ghostship-seerr//server,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-seerr{,//npm},
  }

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/local/bin/node mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/libgcc_s.so.1 mr,
    /usr/lib/libstdc++.so.6.0.34 mr,
    # Native addons mapped by the live server: exact files, no .node glob.
    /app/node_modules/.pnpm/bcrypt@6.0.0/node_modules/bcrypt/prebuilds/linux-arm64/bcrypt.musl.node mr,
    /app/node_modules/.pnpm/sqlite3@5.1.7/node_modules/sqlite3/build/Release/node_sqlite3.node mr,
    /app/node_modules/.pnpm/@next+swc-linux-arm64-musl@16.2.6/node_modules/@next/swc-linux-arm64-musl/next-swc.linux-arm64-musl.node mr,

    # Application code is read-only; no execution of anything.
    /app/ r,
    /app/{package.json,committag.json,next.config.ts,tsconfig.json,postcss.config.js,tailwind.config.js,seerr-api.yml} r,
    /app/{dist,node_modules,.next,public}/ r,
    /app/{dist,node_modules,.next,public}/** r,

    # Settings (with service API keys), SQLite database with WAL and locks,
    # logs and caches.
    /app/config/ r,
    /app/config/** rwk,

    /etc/{hosts,resolv.conf,nsswitch.conf,localtime} r,
    # TZ=Pacific/Honolulu is mapped from here.
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /proc/{stat,meminfo} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq r,
    owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo,stat,statm} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,

    # TCP: the :5055 listener, TMDB/Plex/*arr and notifications; UDP for DNS.
    # unix stream: the stdio socketpair inherited from npm.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-seerr{,//npm},
    signal (send, receive) peer=ghostship-seerr//server,
  }

  # Healthcheck wget and other BusyBox applets. No config or application access.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    /etc/{hosts,resolv.conf,nsswitch.conf,localtime} r,
    audit /proc/sys/kernel/random/boot_id r,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-seerr,
    signal (send, receive) peer=ghostship-seerr//tools,
  }
}
