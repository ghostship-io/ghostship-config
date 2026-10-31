# Container policy: python:3.13-slim-bookworm, Basic Memory 1.0.0 from the
# pre-baked venv at /app/.venv, uid/gid 3000:3000, no capabilities. Mounts:
# /data (rw: config, SQLite, Markdown) and the read-only fastembed cache under
# /opt/agent-memory. The MCP server listens on port 8000 inside the container
# network only; nothing is published.
# Healthcheck: `basic-memory --version`. The collector's heartbeat runs
# /bin/cat on the boot ID.
# Complain mode, like every profile here: unmatched operations stay allowed and
# visible while the policy is refined.
profile ghostship-agent-memory flags=(complain,attach_disconnected,mediate_deleted) {
  /usr/local/bin/python3.13 mr,
  /usr/local/bin/python3 mr,
  /app/.venv/bin/python3.13 mr,
  /bin/{cat,sh,dash} mr,
  /usr/bin/{cat,sh,dash} mr,
  /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 mr,
  /usr/lib/aarch64-linux-gnu/lib{c.so.6,dl.so.2,m.so.6,pthread.so.0,gcc_s.so.1,stdc++.so.6.0.30,util.so.1,z.so.1} mr,
  /etc/ld.so.cache r,

  /app/.venv/ r,
  /app/.venv/** r,
  /app/src/ r,
  /app/src/** r,
  /opt/agent-memory/ r,
  /opt/agent-memory/** r,

  /data/ r,
  /data/** rwk,
  /tmp/ r,
  /tmp/** rwkl,

  /dev/{null,urandom,zero} rw,
  /proc/{stat,cpuinfo,meminfo} r,
  /proc/self/** r,
  /sys/devices/system/cpu/{online,possible,present} r,
  /etc/{hosts,resolv.conf,nsswitch.conf,gai.conf,passwd,group,localtime} r,
  /etc/ssl/** r,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  network inet stream,
  network inet6 stream,
  network unix stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-agent-memory,
}
