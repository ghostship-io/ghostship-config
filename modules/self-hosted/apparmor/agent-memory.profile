# Container policy for the shared Basic Memory service (#1676), derived from
# modules/self-hosted/agent-memory.Containerfile and upstream
# basicmachines-co/basic-memory @ c9bd187b83baba549d5cd16bacc180f8023d51c8.
# Image: python:3.13-slim-bookworm, one non-editable venv at /app/.venv, model at
# /opt/agent-memory/fastembed_cache, user 3000:3000, no capabilities, no shell
# in the command. Enforced, not complain: allow only the image's Python trees,
# the private data volume, /tmp and the service network.
# A live scratch exec/open readback (no network) is requested from the release
# owner before activation; any observed path outside this allowlist is a STOP.
profile ghostship-agent-memory flags=(attach_disconnected,mediate_deleted) {
  # Entrypoints: the console script, the venv Python (symlink to
  # /usr/local/bin/python3.13) and the project-bootstrap CLI.
  /app/.venv/bin/basic-memory rix,
  /app/.venv/bin/python rix,
  /app/.venv/bin/python3 rix,
  /app/.venv/bin/python3.13 rix,
  /usr/local/bin/python3.13 rix,

  # Image code and libraries: read/mmap; .so files need m for executable maps.
  /app/ r,
  /app/** mr,
  /app/**/*.so* mr,
  /opt/agent-memory/ r,
  /opt/agent-memory/** mr,
  /usr/local/lib/ r,
  /usr/local/lib/** mr,
  /usr/lib/ r,
  /usr/lib/** mr,
  /lib/ r,
  /lib/** mr,

  # Private data volume: config, SQLite (with -wal/-shm) and Markdown.
  /data/ rw,
  /data/** rwk,

  # Temporary files: tempfile, SQLite and tokenizer spooling.
  /tmp/ rw,
  /tmp/** rwk,

  / r,
  /{etc,usr,usr/local,opt,dev,proc,sys}/ r,
  /etc/{passwd,group,hosts,host.conf,resolv.conf,nsswitch.conf,services,protocols,localtime,timezone,os-release,ssl} r,
  /etc/ssl/** r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self,[0-9]*}/{stat,status,statm,cmdline,maps,mounts,mountinfo,cgroup} r,
  /proc/{self,thread-self,[0-9]*}/fd/ r,
  /proc/{self,thread-self,[0-9]*}/fd/[0-9]* rw,
  /proc/{cpuinfo,meminfo,stat} r,
  /sys/devices/system/cpu/{online,possible,present} r,
  /sys/devices/system/cpu/** r,
  /sys/class/drm/** r,
  audit /proc/sys/kernel/random/boot_id r,

  # MCP on 0.0.0.0:8000 over ghostship_net, plus DNS. AppArmor cannot restrict
  # destinations or ports; the network membership and no published port do.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-agent-memory,
}
