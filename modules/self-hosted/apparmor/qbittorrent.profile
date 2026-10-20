# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer qBittorrent 5.2.4_v2.0.15-ls481 (lscr.io/linuxserver/qbittorrent:latest),
# Alpine 3.24.2 (musl); s6-overlay 3.2.1.0; /app/qbittorrent-nox is static.
# s6 and the LinuxServer init run as root (CapEff 0x800405fb); the app runs
# as abc 3000:3000 (supplementary group 1000 "users") via s6-setuidgid.
# Shares gluetun's network namespace (binds tun0); Web UI is VueTorrent from
# the read-only /vuetorrent bind. qBittorrent.conf: [AutoRun] is disabled with
# an empty program; nova3 has no search engines installed, so no Python runs.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_qbittorrent_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_qbittorrent_dl} = /downloads/Torrent

profile ghostship-qbittorrent flags=(complain,attach_disconnected,mediate_deleted) {
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
  @{ghostship_qbittorrent_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_qbittorrent_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_qbittorrent_s6}/etc/** r,
  @{ghostship_qbittorrent_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_qbittorrent_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/ r,
  /etc/s6-overlay/s6-rc.d/ r,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-qbittorrent-config,svc-cron,svc-qbittorrent}/run rix,
  # S6_STAGE2_HOOK and the LinuxServer bash wrapper around /command/with-contenv.
  # /docker-mods would rewrite /usr/bin/with-contenv only if it were missing or
  # a symlink; it is a regular file here, so no write to it is allowlisted.
  /docker-mods rix,
  /usr/bin/with-contenv rix,
  # init-adduser/init-crontab-config/init-qbittorrent-config ownership repair.
  /usr/bin/lsiown rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-qbittorrent}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-qbittorrent}/run rix,

  # Bash, the coreutils multicall (cat, cp, chown, mkdir, id, stat, tee, ...),
  # findutils find (lsiown, init-envfile) and shadow's usermod/groupmod
  # (init-adduser re-ids abc to PUID/PGID 3000 on every start).
  /bin/bash rix,
  /bin/coreutils rix,
  /usr/bin/find rix,
  /usr/sbin/{usermod,groupmod} rix,
  # BusyBox is /init's and the healthcheck's /bin/sh interpreter (entered by
  # crun/podman exec, not by an exec rule). Applets exec'd by path (crontab,
  # crond, wget, `busybox`) and GNU grep (init's /proc/mounts test and the
  # svc's `grep -Po` WebUI\Address lookup) go to the tools domain instead.
  /bin/busybox mr,
  /bin/busybox cx -> tools,
  /bin/grep cx -> tools,
  # s6-notifyoncheck's `nc -z localhost 5000` readiness probe.
  /usr/bin/nc cx -> readiness,
  # svc-qbittorrent: `s6-setuidgid abc /app/qbittorrent-nox --webui-port=5000`.
  /app/qbittorrent-nox cx -> server,

  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/lib{ncursesw.so.6.6,readline.so.8.3,acl.so.1.1.2302,attr.so.1.1.2502,crypto.so.3,skarnet.so.2.15.0.0,utmps.so.0.1.3.3,bsd.so.0.12.2,md.so.0.2.0} mr,

  # Root startup: s6-setuidgid/s6-applyuidgid drop to abc, lsiown/chown and
  # usermod rewrite ownership and account files, s6-supervise signals the
  # uid-3000 service. No net_*, sys_* or mknod.
  capability chown,
  capability dac_override,
  capability fowner,
  capability setuid,
  capability setgid,
  capability kill,

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
  /etc/s6-overlay/s6-rc.d/init-adduser/branding rw,

  # usermod/groupmod: shadow's commonio writes name+ and name-, and locks via a
  # name.<pid> file hard-linked to name.lock. Home is pointed at /root first.
  /etc/{passwd,group,shadow,gshadow} rw,
  /etc/{passwd,group,shadow,gshadow}{-,+} rw,
  /etc/{passwd,group,shadow,gshadow}.lock rwl,
  /etc/{passwd,group,shadow,gshadow}.[0-9]* rwl,
  /etc/{login.defs,subuid,subgid} r,
  /root/ r,

  # lsiown -R abc:abc /config traverses the tree and chowns only mismatches.
  # Directory traversal is allowed; file reads are deliberately NOT allowed
  # (qBittorrent.conf holds the Web UI credential hash): per-file getattr
  # records from this walk are expected during complain-mode review.
  /config/ rw,
  /config/**/ r,
  /app/ rw,
  /defaults/ rw,
  # init-qbittorrent-config: mkdir -p, then copy the default config if missing.
  /config/qBittorrent/ rw,
  /config/qBittorrent/qBittorrent.conf rw,
  /defaults/qBittorrent.conf r,
  # init-qbittorrent-config: `lsiown abc:abc /downloads` (top directory only;
  # the CIFS/NFS-backed share currently keeps uid 1100, so the chown fails).
  /downloads/ rw,
  # init-crontab-config: lsiown root:root /etc/crontabs/root before import.
  /etc/crontabs/ r,
  /etc/crontabs/{abc,root} rw,
  # init-migrations, init-custom-files and the mod installer only test these;
  # the image has no migrations, custom scripts or mod lists.
  /migrations/ r,
  /custom-cont-init.d/ r,
  /custom-services.d/ r,
  /mod-{pip,repo}-packages-to-install.list r,

  / r,
  /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
  /etc/{hosts,resolv.conf,nsswitch.conf,localtime,os-release} r,
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
  signal (send, receive) peer=ghostship-qbittorrent,
  signal (send, receive) peer=ghostship-qbittorrent//server,
  signal (send, receive) peer=ghostship-qbittorrent//readiness,
  signal (send, receive) peer=ghostship-qbittorrent//tools,

  # Static qbittorrent-nox (Qt + libtorrent + OpenSSL). No execs at all: AutoRun
  # is disabled and search plugins (python3 nova2.py) are not installed.
  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    /app/qbittorrent-nox rm,

    # XDG config/data/cache under /config: qBittorrent.conf, BT_backup,
    # categories, GeoDB, RSS, logs, lockfile and the ipc-socket (QLocalServer).
    # /config/qBittorrent/nova3 holds Python search helpers written by the app;
    # nothing here may execute them.
    /config/ rw,
    /config/** rwk,
    # Alternative Web UI (VueTorrent), read-only Nix store bind.
    /vuetorrent/ r,
    /vuetorrent/** r,
    # Save/Temp paths and category subfolders (sonarr, radarr, prowlarr, ...).
    /downloads/ r,
    @{ghostship_qbittorrent_dl}/ rw,
    @{ghostship_qbittorrent_dl}/** rwk,

    / r,
    /{etc,usr,usr/share,dev,proc}/ r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,services,protocols,localtime,os-release} r,
    /usr/lib/os-release r,
    /etc/ssl/ r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/ca-certificates.crt r,
    /etc/ssl/openssl.cnf r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    # QStorageInfo free-space and mount lookups for the save path.
    owner /proc/{self,thread-self,[0-9]*}/mountinfo r,

    # Web UI on :5000, BitTorrent TCP/uTP/DHT/LSD on tun0 (IPv4 and IPv6),
    # NETLINK_ROUTE (SOCK_DGRAM) interface enumeration for Session\Interface,
    # and the unix-stream IPC socket. AppArmor cannot restrict destinations.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink dgram,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-qbittorrent,
    signal (send, receive) peer=ghostship-qbittorrent//server,
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
    signal (receive) peer=ghostship-qbittorrent,
    signal (send, receive) peer=ghostship-qbittorrent//readiness,
  }

  # BusyBox applets and GNU grep exec'd by path, all as root: /docker-mods'
  # and init's /proc/mounts greps; svc-qbittorrent's WebUI\Address lookup in
  # qBittorrent.conf; crontab import and probes; the resident crond
  # (setuid/setgid to run jobs) and its `sh -c run-parts /etc/periodic/*`
  # (all five directories are empty); the podman healthcheck's wget to
  # loopback. AppArmor cannot select applets by argv, so this domain also
  # covers sh. No other /config access, no app tree.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /bin/grep rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/libpcre2-8.so.0.16.1 mr,
    capability setuid,
    capability setgid,
    /config/qBittorrent/qBittorrent.conf r,
    /etc/crontabs/ r,
    /etc/crontabs/{abc,root} rw,
    /etc/crontabs/{abc,root}.new rw,
    /etc/crontabs/cron.update rw,
    /etc/periodic/ r,
    /etc/periodic/{15min,hourly,daily,weekly,monthly}/ r,
    /run/crond.{pid,reboot} rw,
    /etc/{passwd,group,shadow,hosts,resolv.conf} r,
    /proc/{self,thread-self,[0-9]*}/mounts r,
    /dev/null rw,
    network inet stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-qbittorrent,
    signal (send, receive) peer=ghostship-qbittorrent//tools,
  }
}
