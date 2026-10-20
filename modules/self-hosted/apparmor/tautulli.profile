# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer Tautulli v2.18.2-ls248 (lscr.io/linuxserver/tautulli:latest),
# Alpine 3.24.2 (musl), Python 3.14 in the /lsiopy venv; s6-overlay 3.2.1.0.
# Container User 3000:3000: /docker-mods sets LSIO_NON_ROOT_USER, so every
# LinuxServer script takes its non-root branch (no usermod, lsiown, crontab
# install or s6-setuidgid). CapEff=0 for every process: no capability rules.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_tautulli_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_tautulli_py} = /usr/lib/python3.14
@{ghostship_tautulli_site} = /lsiopy/lib/python3.14/site-packages

profile ghostship-tautulli flags=(complain,attach_disconnected,mediate_deleted) {
  # s6-overlay stage0/1/2, s6-rc oneshots and supervision. Execline and the
  # portable/linux utilities are multicall binaries; s6 binaries are static.
  # Do not allow all of /command or /package.
  /init rix,
  /package/admin/execline-2.9.7.0/command/execline rix,
  /package/admin/s6-portable-utils-2.3.1.0/command/s6-portable-utils rix,
  /package/admin/s6-linux-utils-2.6.3.0/command/s6-linux-utils rix,
  /package/admin/s6-overlay-helpers-0.1.2.0/command/{s6-overlay-stat,s6-overlay-suexec} rix,
  /package/admin/s6-2.13.2.0/command/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-notify,s6-envdir,s6-envuidgid,s6-setuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-ipcclient,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.6.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.1.3.0/command/{s6-linux-init,s6-linux-init-maker,s6-linux-init-shutdownd,s6-linux-init-hpr,s6-linux-init-nuke,s6-linux-init-umountall} rix,
  @{ghostship_tautulli_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_tautulli_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_tautulli_s6}/etc/** r,
  @{ghostship_tautulli_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_tautulli_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/ r,
  /etc/s6-overlay/s6-rc.d/ r,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-tautulli-config,svc-cron,svc-tautulli}/run rix,
  # S6_STAGE2_HOOK and the LinuxServer bash wrapper around /command/with-contenv.
  /docker-mods rix,
  /usr/bin/with-contenv rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-tautulli}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-tautulli}/run rix,

  # Bash and the coreutils multicall (cat, cut, id, stat, tee, sleep, ...).
  # The svc-cron bash and its `sleep infinity` stay resident in this domain.
  /bin/bash rix,
  /bin/coreutils rix,
  /usr/bin/find rix,
  # BusyBox is /init's and the healthcheck's /bin/sh interpreter (entered by
  # crun/podman exec, not by an exec rule). Applets exec'd by path (grep,
  # crontab, wget, `busybox`) go to the tools domain instead.
  /bin/busybox mr,
  /bin/busybox cx -> tools,
  # s6-notifyoncheck's `nc -z localhost 8181` readiness probe.
  /usr/bin/nc cx -> readiness,
  # svc-tautulli: `s6-notifyoncheck ... python3 /app/tautulli/Tautulli.py`;
  # python3 resolves through /lsiopy/bin/python3 -> /usr/bin/python3.14.
  /usr/bin/python3.14 cx -> tautulli,

  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/lib{ncursesw.so.6.6,readline.so.8.3,acl.so.1.1.2302,attr.so.1.1.2502,crypto.so.3,skarnet.so.2.15.0.0,utmps.so.0.1.3.3} mr,

  # s6 runtime state, the container environment projection and branding.
  /run/ r,
  /run/s6/ rw,
  /run/s6/** rwk,
  /run/s6-rc rw,
  /run/service/ rw,
  /run/service/** rwk,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwk,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,
  /run/branding rw,
  # init-adduser, init-migrations, init-custom-files and the mod installer only
  # test these; the image has no migrations, custom scripts or mod lists.
  /config/ r,
  /app/ r,
  /defaults/ r,
  /migrations/ r,
  /custom-cont-init.d/ r,
  /custom-services.d/ r,
  /mod-{pip,repo}-packages-to-install.list r,

  / r,
  /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
  /etc/{passwd,group,hosts,resolv.conf,localtime,os-release} r,
  /usr/lib/os-release r,
  /{build_version,donate.txt} r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  # Collector heartbeat: `podman exec <c> /bin/cat` (coreutils) lands here.
  audit /proc/sys/kernel/random/boot_id r,

  # s6rc-oneshot-runner: s6-ipcserverd listens on a unix socket under
  # /run/service and s6-rc's s6-sudo clients connect to it. No IP sockets here.
  network unix stream,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-tautulli,
  signal (send, receive) peer=ghostship-tautulli//tautulli,
  signal (send, receive) peer=ghostship-tautulli//readiness,
  signal (send, receive) peer=ghostship-tautulli//tools,

  # Tautulli under the venv interpreter. Code (/app/tautulli, /lsiopy and the
  # stdlib) is root-owned and read-only to uid 3000. No exec permissions at all:
  # no notifier scripts (the notifiers and newsletters tables are empty), no git
  # (git_path is empty; TAUTULLI_DOCKER disables self-update) and no shell.
  profile tautulli flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/python3.14 rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{python3.14.so.1.0,bz2.so.1.0.8,crypto.so.3,ssl.so.3,expat.so.1.12.5,ffi.so.8.2.0,lzma.so.5.8.4,mpdec.so.4.0.1,sqlite3.so.3.53.4,z.so.1.3.2} mr,
    # Exact stdlib and venv extension modules mapped by the live process.
    @{ghostship_tautulli_py}/lib-dynload/{array,binascii,_bisect,_blake2,_bz2,_codecs_cn,_codecs_hk,_codecs_iso2022,_codecs_jp,_codecs_kr,_codecs_tw,_csv,_ctypes,_decimal,_elementtree,fcntl,grp,_hashlib,_heapq,_hmac,_interpreters,_json,_lzma,math,_multibytecodec,_multiprocessing,_pickle,_posixsubprocess,pyexpat,_queue,_random,select,_socket,_sqlite3,_ssl,_struct,termios,unicodedata,zlib,_zoneinfo}.cpython-314-aarch64-linux-musl.so mr,
    @{ghostship_tautulli_site}/_cffi_backend.cpython-314-aarch64-linux-musl.so mr,
    @{ghostship_tautulli_site}/cryptography/hazmat/bindings/_rust.abi3.so mr,
    @{ghostship_tautulli_site}/cryptography.libs/libgcc_s-2d945d6c.so.1 mr,

    @{ghostship_tautulli_py}/ r,
    @{ghostship_tautulli_py}/** r,
    /lsiopy/ r,
    /lsiopy/** r,
    /app/tautulli/ r,
    /app/tautulli/** r,

    # --datadir /config: config.ini, tautulli.db (+ journal), logs, cache,
    # backups, exports, newsletters and the self-signed HTTPS cert/key.
    /config/ rw,
    /config/** rwk,
    # Read-only bind of Plex's server logs for the log viewer.
    /logs/ r,
    /logs/** r,

    / r,
    /{etc,usr,usr/lib,usr/share,dev,proc}/ r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,services,protocols,localtime,os-release,mime.types} r,
    /usr/lib/os-release r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/ca-certificates.crt r,
    /etc/ssl/openssl.cnf r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,

    # CherryPy on 0.0.0.0:8181, the Plex websocket/API on the bridge, GitHub
    # release checks; musl DNS over UDP. AppArmor cannot restrict destinations.
    network inet stream,
    network inet dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-tautulli,
    signal (send, receive) peer=ghostship-tautulli//tautulli,
  }

  # netcat-openbsd readiness probe to loopback, up to 300 tries 1 s apart.
  profile readiness flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/nc rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{bsd.so.0.12.2,md.so.0.2.0} mr,
    /etc/{hosts,resolv.conf,services} r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-tautulli,
    signal (send, receive) peer=ghostship-tautulli//readiness,
  }

  # BusyBox applets exec'd by path: /docker-mods' grep of /proc/mounts,
  # svc-cron's `crontab -l` probes and applet listing, and the podman
  # healthcheck's wget to loopback. No /config, no app tree, no writes.
  # AppArmor cannot select applets by argv, so this domain also covers sh.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /etc/{passwd,group,hosts,resolv.conf} r,
    /etc/crontabs/ r,
    /etc/crontabs/{abc,root} r,
    /proc/{self,thread-self,[0-9]*}/mounts r,
    /dev/null rw,
    network inet stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-tautulli,
    signal (send, receive) peer=ghostship-tautulli//tools,
  }
}
