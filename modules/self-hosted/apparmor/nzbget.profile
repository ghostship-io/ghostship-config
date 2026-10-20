# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer NZBGet v26.3-ls268 (lscr.io/linuxserver/nzbget:latest),
# Alpine 3.24.2 (musl); s6-overlay 3.2.1.0.
# Container User 3000:3000: /docker-mods sets LSIO_NON_ROOT_USER, so every
# LinuxServer script takes its non-root branch (no usermod, lsiown, chmod,
# crontab install or s6-setuidgid). CapEff=0 for every process: no capability rules.
# nzbget.conf: Unpack/DirectUnpack=yes with UnrarCmd=unrar and SevenZipCmd=7z
# (PATH: /usr/bin/unrar, /usr/bin/7z -> 7zz); par2 repair is built in.
# Extensions= and ScriptOrder= are empty and no category sets Extensions, so no
# post-processing, scan, queue or feed script runs; ShellOverride is empty.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_nzbget_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_nzbget_app} = /app/nzbget
@{ghostship_nzbget_usenet} = /downloads/Usenet

profile ghostship-nzbget flags=(complain,attach_disconnected,mediate_deleted) {
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
  @{ghostship_nzbget_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_nzbget_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_nzbget_s6}/etc/** r,
  @{ghostship_nzbget_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_nzbget_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/ r,
  /etc/s6-overlay/s6-rc.d/ r,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-nzbget-config,svc-cron,svc-nzbget}/run rix,
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
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-nzbget}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-nzbget}/run rix,

  # Bash and the coreutils multicall (cat, cp, rm, id, stat, tee, sleep, ...).
  # The svc-cron bash and its `sleep infinity` stay resident in this domain.
  /bin/bash rix,
  /bin/coreutils rix,
  /usr/bin/find rix,
  # BusyBox is /init's and the healthcheck's /bin/sh interpreter (entered by
  # crun/podman exec, not by an exec rule). Applets exec'd by path (grep,
  # crontab, wget, `busybox`) go to the tools domain instead.
  /bin/busybox mr,
  /bin/busybox cx -> tools,
  # s6-notifyoncheck's `nc -z localhost 6789` readiness probe.
  /usr/bin/nc cx -> readiness,
  # svc-nzbget: `s6-notifyoncheck ... /app/nzbget/nzbget -s -c /config/nzbget.conf`.
  @{ghostship_nzbget_app}/nzbget cx -> server,

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
  # init-nzbget-config: seed nzbget.conf only when missing; remove a stale lock.
  /config/ r,
  /config/nzbget.conf rw,
  /config/nzbget.lock rw,
  @{ghostship_nzbget_app}/share/nzbget/nzbget.conf r,
  # init-adduser, init-migrations, init-custom-files and the mod installer only
  # test these; the image has no migrations, custom scripts or mod lists.
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
  signal (send, receive) peer=ghostship-nzbget,
  signal (send, receive) peer=ghostship-nzbget//server,
  signal (send, receive) peer=ghostship-nzbget//readiness,
  signal (send, receive) peer=ghostship-nzbget//tools,
  signal (send, receive) peer=ghostship-nzbget//extract,

  # NZBGet daemon from the root-owned, read-only app tree. Its only execs are
  # the configured unpackers, in their own domain. No shell, no scripts.
  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    @{ghostship_nzbget_app}/nzbget rm,
    /usr/bin/unrar px -> ghostship-nzbget//extract,
    /usr/bin/7zz px -> ghostship-nzbget//extract,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{boost_json.so.1.84.0,crypto.so.3,ssl.so.3,gcc_s.so.1,lzma.so.5.8.4,ncursesw.so.6.6,stdc++.so.6.0.34,xml2.so.2.13.9,z.so.1.3.2} mr,
    # WebDir, ConfigTemplate and CertStore live in the app tree.
    @{ghostship_nzbget_app}/ r,
    @{ghostship_nzbget_app}/** r,

    # MainDir=/config: nzbget.conf, nzb/, queue/, tmp/ (TempDir), the log and
    # the lock file.
    /config/ rw,
    /config/** rwk,
    # ScriptDir=/scripts is enumerated for the settings page only; nothing is
    # configured to run, so it is read-only and never executable.
    /scripts/ r,
    /scripts/** r,
    # DestDir/InterDir and the appended category directories live here.
    /downloads/ r,
    @{ghostship_nzbget_usenet}/ rw,
    @{ghostship_nzbget_usenet}/** rwk,

    / r,
    /{etc,usr,usr/lib,usr/share,dev,proc}/ r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,services,protocols,localtime,os-release} r,
    /usr/lib/os-release r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/ca-certificates.crt r,
    /etc/ssl/openssl.cnf r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,

    # Web UI/RPC on 0.0.0.0:5001 and TLS to the news server (port 443); musl
    # DNS over UDP. AppArmor cannot restrict destinations or ports.
    network inet stream,
    network inet dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-nzbget,
    signal (send, receive) peer=ghostship-nzbget//server,
    signal (send, receive) peer=ghostship-nzbget//extract,
  }

  # unrar (static) and 7-Zip: unpack archives in InterDir/DestDir. No /config,
  # no /scripts, no network and no further execs.
  profile extract flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/unrar rm,
    /usr/bin/7zz rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{stdc++.so.6.0.34,gcc_s.so.1} mr,
    /downloads/ r,
    @{ghostship_nzbget_usenet}/ rw,
    @{ghostship_nzbget_usenet}/** rw,
    /etc/{passwd,group,localtime} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-nzbget,
    signal (receive) peer=ghostship-nzbget//server,
    signal (send, receive) peer=ghostship-nzbget//extract,
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
    signal (receive) peer=ghostship-nzbget,
    signal (send, receive) peer=ghostship-nzbget//readiness,
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
    signal (receive) peer=ghostship-nzbget,
    signal (send, receive) peer=ghostship-nzbget//tools,
  }
}
