# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# lscr.io/linuxserver/mariadb (sha256:94f67a7e6deb...), LinuxServer
# 11.8.8-r0-ls229, Alpine/musl; s6-overlay 3.2.1.0. Runs as uid/gid 3000
# (LSIO_NON_ROOT_USER path: no usermod/lsiown/chown), no effective
# capabilities, so no capability rules are granted.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Domains: top = s6-overlay + LSIO init scripts + podman healthcheck shell;
# safe = /usr/bin/mariadbd-safe (BusyBox sh) and its helpers; server =
# mariadbd (datadir, socket, tmpdir, configured logs); client = mariadb-admin
# (healthcheck ping, poststart version probe); upgrade = the poststart
# `mariadb-upgrade --check-if-upgrade-is-needed`.

@{romm_db_s6} = /package/admin/s6-overlay-3.2.1.0

profile ghostship-romm-db flags=(complain,attach_disconnected,mediate_deleted) {
  # Shell arguments/inline commands cannot be filtered by AppArmor. Read
  # permissions also permit Bash to interpret a file.
  /init rix,
  /docker-mods rix,
  /bin/{bash,busybox,coreutils} rix,
  /usr/bin/{env,find,with-contenv,nc} rix,

  # Version-pinned s6 executables (static). execline and the portable/linux
  # utilities are multicall binaries; do not allow all of /command or /package.
  /package/admin/execline-2.9.7.0/command/execline rix,
  /package/admin/s6-portable-utils-2.3.1.0/command/s6-portable-utils rix,
  /package/admin/s6-linux-utils-2.6.3.0/command/s6-linux-utils rix,
  /package/admin/s6-overlay-helpers-0.1.2.0/command/{s6-overlay-stat,s6-overlay-suexec} rix,
  /package/admin/s6-2.13.2.0/command/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-notify,s6-envdir,s6-setuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-ipcclient,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.6.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.1.3.0/command/{s6-linux-init,s6-linux-init-maker,s6-linux-init-shutdownd,s6-linux-init-hpr,s6-linux-init-nuke,s6-linux-init-umountall} rix,
  @{romm_db_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo,with-retries} rix,
  @{romm_db_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{romm_db_s6}/etc/** r,
  @{romm_db_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{romm_db_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-mariadb-config,init-mariadb-initdb,init-mariadb-poststart,init-migrations,init-mods-package-install,svc-cron,svc-mariadb}/run rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # entrypoints are an intentional, limited code-loading risk; never extend
  # this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-mariadb}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-mariadb}/run rix,

  /usr/bin/mariadbd-safe cx -> safe,
  # Healthcheck `mariadb-admin ping -h 127.0.0.1` and init-mariadb-poststart.
  /usr/bin/mariadb-admin cx -> client,
  /usr/bin/mariadb-upgrade cx -> upgrade,
  # First-run init-mariadb-initdb starts mariadbd directly (not observed:
  # the datadir is initialised). mariadb-install-db/mktemp are not allowlisted.
  /usr/bin/mariadbd px -> ghostship-romm-db//server,

  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/{libncursesw.so.6.6,libreadline.so.8.3,libacl.so.1.1.2302,libattr.so.1.1.2502,libcrypto.so.3,libskarnet.so.2.15.0.0,libutmps.so.0.1.3.3,libbsd.so.0.12.2,libmd.so.0.2.0} mr,

  # s6 runtime state.
  /run/ r,
  /run/s6/ rw,
  /run/s6/** rwk,
  /run/service/ rw,
  /run/service/** rwk,
  /run/s6-rc rw,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwk,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,
  /run/branding rw,

  # init-mariadb-config: mkdir datadir/log/socket dirs, seed custom.cnf,
  # remove an orphan pid file. initdb/poststart only test these paths.
  /config/ r,
  /config/custom.cnf rw,
  /config/databases/ rw,
  /config/databases/mysql/ r,
  /config/log/ rw,
  /config/log/mysql/ rw,
  /config/env r,
  /defaults/ r,
  /defaults/custom.cnf r,
  /run/mysqld/ rw,
  /run/mysqld/mysqld.pid rw,
  /config/.migrations r,

  / r,
  /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
  /etc/{passwd,group,hosts,hostname,resolv.conf,localtime,os-release,services,protocols} r,
  /etc/crontabs/ r,
  /{build_version,donate.txt} r,
  /usr/share/zoneinfo/** r,
  /proc/mounts r,
  /proc/{self,thread-self}/{mounts,mountinfo,stat,cwd} r,
  /proc/[0-9]*/cwd r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,
  # s6-notifyoncheck's `nc -z localhost 3306` readiness probe and resolver.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network unix stream,
  network unix dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-romm-db,
  signal (send) peer=ghostship-romm-db//{safe,server,client,upgrade},

  profile safe flags=(complain,attach_disconnected,mediate_deleted) {
    # mariadbd-safe: parse defaults, manage the pid file/socket dir and error
    # log header, then `nohup /usr/bin/mariadbd ...` into the server domain.
    /usr/bin/mariadbd-safe r,
    /bin/{busybox,coreutils,ps} rix,
    /usr/bin/my_print_defaults rix,
    /usr/bin/mariadbd px -> ghostship-romm-db//server,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libacl.so.1.1.2302,libattr.so.1.1.2502,libcrypto.so.3,libskarnet.so.2.15.0.0,libutmps.so.0.1.3.3,libintl.so.8.4.6,libproc2.so.1.0.1} mr,
    /etc/my.cnf r,
    /etc/my.cnf.d/ r,
    /etc/my.cnf.d/mariadb-server.cnf r,
    /config/custom.cnf r,
    /config/databases/ r,
    /config/log/mysql/ r,
    /config/log/mysql/mariadb-error.log rw,
    /run/mysqld/ rw,
    /run/mysqld/mysqld.pid rw,
    /run/mysqld/mysqld.sock rw,
    /usr/share/mariadb/ r,
    # ps wwwp/xaww process checks.
    /proc/ r,
    /proc/[0-9]*/{stat,status,cmdline,environ} r,
    /proc/{uptime,meminfo,stat,loadavg} r,
    /proc/sys/kernel/{pid_max,osrelease} r,
    / r,
    /etc/{passwd,group,localtime} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm-db,
    signal (send, receive) peer=ghostship-romm-db//safe,
    signal (send) peer=ghostship-romm-db//server,
  }

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # mariadbd: exactly its datadir, unix socket/pid file, tmpdir (/tmp) and
    # the log_error/slow/binlog files custom.cnf places under /config/log/mysql.
    /usr/bin/mariadbd mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libaio.so.1.0.2,libcrypto.so.3,libgcc_s.so.1,libpcre2-8.so.0.15.0,libssl.so.3,libstdc++.so.6.0.34,libz.so.1.3.2} mr,
    /etc/my.cnf r,
    /etc/my.cnf.d/ r,
    /etc/my.cnf.d/mariadb-server.cnf r,
    /config/custom.cnf r,
    /usr/share/mariadb/ r,
    /usr/share/mariadb/** r,
    /config/databases/ rw,
    /config/databases/** rwk,
    /config/log/mysql/ rw,
    /config/log/mysql/** rwk,
    /run/mysqld/ r,
    /run/mysqld/mysqld.pid rw,
    /run/mysqld/mysqld.sock rw,
    /tmp/ r,
    /tmp/** rwk,
    / r,
    /etc/{passwd,group,hosts,resolv.conf,localtime} r,
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
    /sys/devices/system/node/ r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,
    # Port 3306 on IPv4/IPv6 for romm, plus the local unix socket.
    network inet stream,
    network inet6 stream,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm-db,
    signal (receive) peer=ghostship-romm-db//safe,
    signal (send, receive) peer=ghostship-romm-db//server,
  }

  profile client flags=(complain,attach_disconnected,mediate_deleted) {
    # mariadb-admin ping/version: client config and a TCP or socket probe.
    /usr/bin/mariadb-admin mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libcrypto.so.3,libssl.so.3,libz.so.1.3.2} mr,
    /etc/my.cnf r,
    /etc/my.cnf.d/ r,
    /etc/my.cnf.d/mariadb-server.cnf r,
    /etc/{passwd,group,hosts,resolv.conf,localtime} r,
    /etc/ssl/openssl.cnf r,
    /usr/share/mariadb/** r,
    /run/mysqld/mysqld.sock rw,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    network inet stream,
    network inet6 stream,
    network unix stream,
    audit /proc/sys/kernel/random/boot_id r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm-db,
    signal (send, receive) peer=ghostship-romm-db//client,
  }

  profile upgrade flags=(complain,attach_disconnected,mediate_deleted) {
    # mariadb-upgrade --check-if-upgrade-is-needed: probes its sibling tools
    # through popen (`sh -c "mariadb --help ..."`), queries the server, and
    # reads the datadir's upgrade marker. No datadir writes.
    /usr/bin/mariadb-upgrade mr,
    /bin/busybox rix,
    /usr/bin/{mariadb,mariadb-check} rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libcrypto.so.3,libgcc_s.so.1,libncursesw.so.6.6,libssl.so.3,libstdc++.so.6.0.34,libz.so.1.3.2} mr,
    /etc/my.cnf r,
    /etc/my.cnf.d/ r,
    /etc/my.cnf.d/mariadb-server.cnf r,
    /config/databases/{mariadb_upgrade_info,mysql_upgrade_info} r,
    /etc/{passwd,group,hosts,resolv.conf,localtime} r,
    /usr/share/mariadb/** r,
    /run/mysqld/mysqld.sock rw,
    /tmp/ r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    network inet stream,
    network inet6 stream,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm-db,
    signal (send, receive) peer=ghostship-romm-db//upgrade,
  }
}
