# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/library/mariadb (sha256:2439dcd7d140...), MariaDB 11.8.9
# (1:11.8.9+maria~ubu2404) on Ubuntu 24.04; entrypoint
# /usr/local/bin/docker-entrypoint.sh, CMD mariadbd. Runs as uid/gid 3000
# (no gosu switch), no effective capabilities, so no capability rules.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Domains: top = docker-entrypoint.sh (bash) and the podman healthcheck's
# `sh -c` (dash); server = every mariadbd exec (the entrypoint's
# `--verbose --help` config probes and the final `exec mariadbd`); client =
# healthcheck `mariadb-admin ping -h 127.0.0.1`. The first-run initialisation
# and docker_mariadb_upgrade paths (mariadb-install-db, temporary server,
# mariadb client/upgrade/backup) are not allowlisted: the datadir exists and
# mariadb_upgrade_info is current; they would be logged in complain mode.

@{gdb_lib} = /usr/lib/aarch64-linux-gnu

profile ghostship-grimmory-db flags=(complain,attach_disconnected,mediate_deleted) {
  /usr/local/bin/docker-entrypoint.sh rix,
  /usr/bin/{bash,dash} rix,
  # mysql_log's `date`, docker_create_db_directories' `id -u`/`mkdir -p`, and
  # mysql_get_config's `awk` (gawk via alternatives).
  /usr/bin/{date,id,mkdir,gawk} rix,
  /usr/sbin/mariadbd cx -> server,
  /usr/bin/mariadb-admin cx -> client,

  @{gdb_lib}/ld-linux-aarch64.so.1 mr,
  @{gdb_lib}/{libc.so.6,libm.so.6,libtinfo.so.6.4,libpcre2-8.so.0.11.2,libselinux.so.1,libgmp.so.10.5.0,libmpfr.so.6.2.1,libreadline.so.8.2,libsigsegv.so.2.0.7} mr,

  # `mkdir -p "$DATADIR"` and `[ -d "$DATADIR/mysql" ]` / upgrade-marker reads.
  /var/lib/mysql/ r,
  /var/lib/mysql/mysql/ r,
  /var/lib/mysql/{mariadb_upgrade_info,.my-healthcheck.cnf} r,

  / r,
  /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache} r,
  /usr/share/zoneinfo/** r,
  /usr/lib/locale/** r,
  /dev/null rw,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-grimmory-db,
  signal (send) peer=ghostship-grimmory-db//{server,client},

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # mariadbd: exactly its datadir, socket/pid file and tmpdir (/tmp). The
    # error log goes to stderr; no plugin directory mappings were observed.
    /usr/sbin/mariadbd mr,
    @{gdb_lib}/ld-linux-aarch64.so.1 mr,
    @{gdb_lib}/{libaio.so.1t64.0.2,libc.so.6,libcap.so.2.66,libcrypt.so.1.1.0,libcrypto.so.3,libgcc_s.so.1,libgcrypt.so.20.4.3,libgpg-error.so.0.34.0,liblz4.so.1.9.4,liblzma.so.5.4.5,libm.so.6,libpcre2-8.so.0.11.2,libssl.so.3,libstdc++.so.6.0.33,libsystemd.so.0.38.0,liburing.so.2.5,libz.so.1.3,libzstd.so.1.5.5} mr,
    /etc/ld.so.cache r,
    /etc/mysql/ r,
    /etc/mysql/mariadb.cnf r,
    /etc/mysql/conf.d/ r,
    /etc/mysql/mariadb.conf.d/ r,
    /etc/mysql/mariadb.conf.d/*.cnf r,
    /usr/share/mariadb/ r,
    /usr/share/mariadb/** r,
    /var/lib/mysql/ rw,
    /var/lib/mysql/** rwk,
    /run/mysqld/ r,
    /run/mysqld/mysqld.pid rw,
    /run/mysqld/mysqld.sock rw,
    /tmp/ r,
    /tmp/** rwk,
    / r,
    /etc/{passwd,group,nsswitch.conf,hosts,resolv.conf,localtime} r,
    /usr/share/zoneinfo/ r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/urandom r,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{status,stat,mounts,mountinfo,cgroup} r,
    /proc/{meminfo,cpuinfo,stat} r,
    /proc/sys/kernel/{osrelease,pid_max} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high,memory.pressure} r,
    # Port 3306 on IPv4/IPv6 for grimmory, plus the local unix socket.
    network inet stream,
    network inet6 stream,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-grimmory-db,
    signal (send, receive) peer=ghostship-grimmory-db//server,
  }

  profile client flags=(complain,attach_disconnected,mediate_deleted) {
    # Healthcheck: mariadb-admin ping over TCP to 127.0.0.1:3306.
    /usr/bin/mariadb-admin mr,
    @{gdb_lib}/ld-linux-aarch64.so.1 mr,
    @{gdb_lib}/{libc.so.6,libcrypto.so.3,libssl.so.3,libz.so.1.3} mr,
    /etc/ld.so.cache r,
    /etc/mysql/ r,
    /etc/mysql/mariadb.cnf r,
    /etc/mysql/conf.d/ r,
    /etc/mysql/mariadb.conf.d/ r,
    /etc/mysql/mariadb.conf.d/*.cnf r,
    /etc/ssl/openssl.cnf r,
    /etc/{passwd,group,nsswitch.conf,hosts,resolv.conf,localtime} r,
    /usr/share/mariadb/** r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-grimmory-db,
    signal (send, receive) peer=ghostship-grimmory-db//client,
  }
}
