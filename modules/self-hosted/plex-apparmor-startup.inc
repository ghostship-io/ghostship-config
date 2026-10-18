# Startup domain only: inspected image scripts, not the server runtime allowlist.
# Shell arguments/inline commands cannot be filtered by AppArmor. Read permissions
# also permit Bash to interpret a file; do not add general writable-script reads.
  /init rix,
  /{,usr/}bin/{bash,dash,sh,env,with-contenv} rix,
  /usr/bin/{cat,chmod,chown,cp,crontab,cut,find,grep,head,id,ln,lsiown,mkdir,readlink,rm,sed,sleep,sort,stat,tr,uname} rix,
  /usr/bin/{awk,mawk,nc.openbsd} rix,
  /usr/sbin/cron rix,

  # Resolve /command symlinks to version-pinned package executables. Execline
  # and the portable/linux utilities are multicall binaries, not shell escapes
  # into an unconfined profile. Do not allow all of /command or /package.
  /package/admin/execline-2.9.7.0/command/execline rix,
  /package/admin/s6-portable-utils-2.3.1.0/command/s6-portable-utils rix,
  /package/admin/s6-linux-utils-2.6.3.0/command/s6-linux-utils rix,
  /package/admin/s6-overlay-helpers-0.1.2.0/command/{s6-overlay-stat,s6-overlay-suexec} rix,
  /package/admin/s6-2.13.2.0/command/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-notify,s6-envdir,s6-setuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-ipcclient,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.6.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.1.3.0/command/{s6-linux-init,s6-linux-init-maker,s6-linux-init-shutdownd,s6-linux-init-hpr,s6-linux-init-nuke,s6-linux-init-umountall} rix,
  @{ghostship_plex_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_plex_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_plex_s6}/etc/** r,
  @{ghostship_plex_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_plex_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{ci-service-check,init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-plex-chown,init-plex-claim,init-plex-update,svc-cron,svc-plex}/run rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-plex}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-plex}/run rix,

  # System loader and libraries for shell/startup utilities. Resolved SONAME
  # symlinks need their on-disk filenames too. Version changes require review.
  /{,usr/}lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 mr,
  /{,usr/}lib/aarch64-linux-gnu/lib{c.so.6,dl.so.2,m.so.6,pthread.so.0,rt.so.1,gcc_s.so.1} mr,
  /{,usr/}lib/aarch64-linux-gnu/lib{tinfo.so.6,tinfo.so.6.6,pcre2-8.so.0,pcre2-8.so.0.14.0,z.so.1,z.so.1.3.1,selinux.so.1,acl.so.1,acl.so.1.1.2302,attr.so.1,attr.so.1.1.2502} mr,

  # Startup owns only s6's generated startup/shutdown scripts. Neither child
  # includes these paths; no child has an exec transition back to startup.
  /run/s6/ rw,
  /run/s6/** rwk,
  /run/service/ rw,
  /run/service/** rwk,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwk,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,

  # init-adduser/init-plex-chown inspect the roots and immediate directories.
  # Recursive ownership repair is deliberately NOT justification for /config/**
  # writes or reads: record any required paths during complain-mode review.
  /config/ rw,
  /config/*/ rw,
  /config/Library/ rw,
  "/config/Library/Application Support/" rw,
  "@{ghostship_plex_state}/" rw,
  "@{ghostship_plex_state}/plexmediaserver.pid" rw,
  "@{ghostship_plex_state}/Preferences.xml" r,
  /app/ r,
  /defaults/ r,
  /defaults/crontabs/ r,
  /defaults/crontabs/{abc,root} r,
  /config/crontabs/ rw,
  /config/crontabs/{abc,root} rw,
  /etc/crontabs/ r,
  /etc/crontabs/{abc,root} r,
  /var/spool/cron/crontabs/ rw,
  /var/spool/cron/crontabs/{abc,root} rw,
  /var/spool/cron/crontabs/tmp.* rw,
  # init-migrations records names. No migration/custom-script execution is
  # allowlisted: the inspected image has no migration/custom script workload.
  /config/.migrations rw,
  /migrations/ r,
  /custom-cont-init.d/ r,
  # init-plex-chown removes/recreates only the configured transient directory.
  /run/plex-temp/ rw,
  /run/plex-temp/** rw,

  / r,
  /{etc,usr,usr/lib,usr/share,run,dev,proc,sys}/ r,
  /etc/{passwd,group,nsswitch.conf,hosts,hostname,resolv.conf,host.conf,gai.conf,ld.so.cache,localtime,timezone,os-release,environment,services,protocols,lsi-release} r,
  /etc/cont-init.d/ r,
  /etc/cont-finish.d/ r,
  /etc/services.d/ r,
  /{build_version,donate.txt} r,
  /usr/lib/locale/** r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/sys/kernel/{hostname,osrelease,ostype} r,
  # Runtime-launched cat probe proves audit delivery without expanding server access.
  audit /proc/sys/kernel/random/boot_id r,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  # svc-plex's nc readiness probe and its resolver; no updater/download tools.
  network inet stream,
  network inet dgram,
  signal (send, receive) peer=ghostship-plex,
  signal (send, receive) peer=ghostship-plex//server,
  signal (send, receive) peer=ghostship-plex//python,
  signal (receive) peer=unconfined,
