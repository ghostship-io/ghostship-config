# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer Prowlarr 2.6.5.5623-ls164 (lscr.io/linuxserver/prowlarr:latest), Prowlarr 2.6.5.5623,
# Alpine 3.24 (musl); s6-overlay 3.2.1.0; uid/gid 3000:3000 (LSIO_NON_ROOT_USER).
# Running as uid 3000 with CapEff=0 for every process: no capability rules.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_prowlarr_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_prowlarr_app} = /app/prowlarr/bin

profile ghostship-prowlarr flags=(complain,attach_disconnected,mediate_deleted) {
  # s6-overlay 3.2.1.0 stage0/1/2, s6-rc oneshots and supervision. Execline and
  # the portable/linux utilities are multicall binaries. Do not allow all of
  # /command or /package.
  /init rix,
  /package/admin/execline-2.9.7.0/command/execline rix,
  /package/admin/s6-portable-utils-2.3.1.0/command/s6-portable-utils rix,
  /package/admin/s6-linux-utils-2.6.3.0/command/s6-linux-utils rix,
  /package/admin/s6-overlay-helpers-0.1.2.0/command/{s6-overlay-stat,s6-overlay-suexec} rix,
  /package/admin/s6-2.13.2.0/command/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-notify,s6-envdir,s6-setuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-ipcclient,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.6.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.1.3.0/command/{s6-linux-init,s6-linux-init-maker,s6-linux-init-shutdownd,s6-linux-init-hpr,s6-linux-init-nuke,s6-linux-init-umountall} rix,
  @{ghostship_prowlarr_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_prowlarr_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_prowlarr_s6}/etc/** r,
  @{ghostship_prowlarr_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_prowlarr_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-prowlarr-config,svc-cron,svc-prowlarr}/run rix,
  # S6_STAGE2_HOOK and the LinuxServer bash wrapper around /command/with-contenv.
  /docker-mods rix,
  /usr/bin/with-contenv rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot,shutdown} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-prowlarr}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-prowlarr}/run rix,

  # The LinuxServer scripts take their LSIO_NON_ROOT_USER branches (uid 3000,
  # /run owned by the user): no usermod/groupmod/lsiown/chown, no mods, no
  # crond (no user crontab), no custom-cont-init.d or migrations. Bash plus the
  # uutils multicall (cat, cut, id, stat, mkdir, tee, sleep, echo, ...) and
  # findutils find (init-envfile). The svc-cron bash and its `sleep infinity`
  # stay resident in this domain.
  /bin/bash rix,
  /bin/coreutils rix,
  /usr/bin/find rix,
  # BusyBox is /init's and the healthcheck's /bin/sh interpreter (entered by
  # crun/podman exec, not by an exec rule). Every BusyBox applet exec'd by path
  # (grep, crontab, wget, `busybox`) goes to the tools domain instead.
  /bin/busybox mr,
  /bin/busybox cx -> tools,

  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/lib{ncursesw.so.6.6,readline.so.8.3,acl.so.1.1.2302,attr.so.1.1.2502,crypto.so.3,skarnet.so.2.15.0.0,utmps.so.0.1.3.3} mr,

  # s6 runtime state and the LinuxServer branding/env projection.
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
  # init-prowlarr-config: `mkdir -p /run/prowlarr-temp` (the server's TMPDIR).
  /run/prowlarr-temp/ rw,
  # init-adduser/init-migrations/init-mods-package-install only test these.
  /config/ r,

  / r,
  /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
  /etc/{passwd,group,hosts,resolv.conf,localtime,timezone,os-release} r,
  /usr/lib/os-release r,
  /{build_version,donate.txt} r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  /proc/sys/kernel/{hostname,osrelease,ostype} r,
  # Collector heartbeat: `podman exec <c> /bin/cat` (uutils) lands here.
  audit /proc/sys/kernel/random/boot_id r,

  # svc-prowlarr: `s6-notifyoncheck ... cd /app/prowlarr/bin /app/prowlarr/bin/Prowlarr`.
  @{ghostship_prowlarr_app}/Prowlarr cx -> server,
  # s6-notifyoncheck's readiness program: s6-rc copies the image's
  # svc-prowlarr/data/check into the writable compiled tree and runs it from there.
  /run/s6-rc:s6-rc-init:*/servicedirs/svc-prowlarr/data/check cx -> readiness,
  /run/s6/db/servicedirs/svc-prowlarr/data/check cx -> readiness,

  # s6rc-oneshot-runner: s6-ipcserverd listens on a unix socket under
  # /run/service and s6-rc's s6-sudo clients connect to it. No IP sockets here:
  # wget (healthcheck) and the readiness probes run in their own domains.
  network unix stream,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-prowlarr,
  signal (send, receive) peer=ghostship-prowlarr//server,
  signal (send, receive) peer=ghostship-prowlarr//readiness,
  signal (send, receive) peer=ghostship-prowlarr//tools,

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # Apphost Prowlarr: the bundled self-contained .NET runtime from the
    # read-only, root-owned app tree. No shell, startup tool, or downloader.
    @{ghostship_prowlarr_app}/Prowlarr rix,
    @{ghostship_prowlarr_app}/ r,
    @{ghostship_prowlarr_app}/** r,
    # 684 managed assemblies are mapped (ReadyToRun code is executable);
    # the set changes every release, so match the flat app directory only.
    @{ghostship_prowlarr_app}/*.dll mr,
    @{ghostship_prowlarr_app}/lib{clrjit,coreclr,e_sqlite3,hostfxr,hostpolicy,MonoPosixHelper,System.IO.Compression.Native,System.Native,System.Security.Cryptography.Native.OpenSsl}.so mr,
    /app/prowlarr/package_info r,

    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{crypto.so.3,ssl.so.3,gcc_s.so.1,stdc++.so.6.0.34,z.so.1.3.2,icudata.so.78.1,icui18n.so.78.1,icuuc.so.78.1} mr,
    /usr/share/icu/78.1/icudt78l.dat r,
    # W^X double mapping: the runtime maps JIT code through this memfd.
    "/memfd:doublemapper" rwm,
    "/memfd:doublemapper (deleted)" rwm,

    # Application state (SQLite with -shm/-wal mappings, logs, MediaCover,
    # Backups, Sentry, XDG_CONFIG_HOME=/config/xdg) and TMPDIR.
    /config/ rw,
    /config/** rwk,
    /run/prowlarr-temp/ rw,
    /run/prowlarr-temp/** rwk,


    / r,
    /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
    /etc/{passwd,group,hosts,resolv.conf,host.conf,nsswitch.conf,services,protocols,localtime,timezone,os-release,fstab,mime.types} r,
    /usr/lib/os-release r,
    /etc/ssl/ r,
    /etc/ssl/** r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdin,stdout,stderr} rw,

    # CoreCLR startup, GC sizing and DriveInfo/mount discovery.
    /proc/{self,thread-self,[0-9]*}/{stat,status,statm,maps,smaps,limits,cmdline,comm,cgroup,mounts,mountinfo} r,
    /proc/{self,thread-self,[0-9]*}/fd/ r,
    /proc/{self,thread-self,[0-9]*}/task/ r,
    /proc/{self,thread-self,[0-9]*}/task/[0-9]*/{stat,status,comm} r,
    /proc/{cpuinfo,meminfo,stat,loadavg,uptime,filesystems} r,
    /proc/sys/kernel/{hostname,osrelease,ostype,pid_max} r,
    /sys/fs/cgroup/ r,
    /sys/fs/cgroup/{cpu.max,cpu.weight,cpuset.cpus.effective,memory.max,memory.high,memory.current,memory.stat} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/cache/** r,

    # Kestrel on [::]:9696 (dual-stack), outbound HTTP(S) to indexers,
    # download clients and metadata services; musl DNS over UDP with TCP
    # fallback; NETLINK_ROUTE for network-change notification; an unnamed
    # unix datagram socket(pair). AppArmor cannot restrict destinations.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink raw,
    network unix dgram,
    signal (receive) peer=unconfined,
    signal (send, receive) peer=ghostship-prowlarr,
    signal (send, receive) peer=ghostship-prowlarr//server,
  }

  # data/check: bash runs xmlstarlet on config.xml for the port, then
  # curl | jq against loopback /ping until ready (300 tries, 1 s apart).
  profile readiness flags=(complain,attach_disconnected,mediate_deleted) {
    /run/s6-rc:s6-rc-init:*/servicedirs/svc-prowlarr/data/check r,
    /run/s6/db/servicedirs/svc-prowlarr/data/check r,
    /bin/bash rix,
    /usr/bin/{xml,curl,jq} rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{ncursesw.so.6.6,readline.so.8.3} mr,
    /usr/lib/lib{exslt.so.0.8.24,xslt.so.1.1.43,xml2.so.2.13.9,lzma.so.5.8.4,z.so.1.3.2} mr,
    /usr/lib/lib{curl.so.4.8.0,brotlicommon.so.1.2.0,brotlidec.so.1.2.0,cares.so.2.19.7,crypto.so.3,ssl.so.3,idn2.so.0.4.0,nghttp2.so.14.29.5,psl.so.5.3.5,unistring.so.5.2.1,zstd.so.1.5.7} mr,
    /usr/lib/lib{jq.so.1.0.4,onig.so.5.5.0} mr,
    # The port lookup reads the whole file, which also holds the API key.
    /config/config.xml r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,services} r,
    /etc/ssl/openssl.cnf r,
    /dev/null rw,
    /proc/{self,thread-self}/fd/ r,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-prowlarr,
    signal (send, receive) peer=ghostship-prowlarr//readiness,
  }

  # BusyBox applets exec'd by path: startup grep (/proc/mounts) and `crontab -l`
  # probes, svc-cron's applet listing, and the podman healthcheck's wget to
  # loopback. No /config, no app tree, no writes. AppArmor cannot select
  # applets by argv, so this domain also covers BusyBox's sh.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /etc/{passwd,group,hosts,resolv.conf} r,
    /proc/{self,thread-self,[0-9]*}/mounts r,
    /dev/null rw,
    network inet stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-prowlarr,
    signal (send, receive) peer=ghostship-prowlarr//tools,
  }
}
