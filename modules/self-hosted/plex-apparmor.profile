# Container policy, inspected on chill-penguin (aarch64), 2026-10-18:
# LinuxServer Plex 1.43.4.10903; s6-overlay 3.2.1.0; uid/gid 3000.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# A policy change restarts that observation window; elapsed time alone is not proof.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.

@{ghostship_plex_pms} = /usr/lib/plexmediaserver
@{ghostship_plex_state} = "/config/Library/Application Support/Plex Media Server"
@{ghostship_plex_s6} = /package/admin/s6-overlay-3.2.1.0

profile ghostship-plex flags=(complain,attach_disconnected,mediate_deleted) {
  # All executions inherit this policy. Missing execution permissions in complain
  # mode are observations to review, not an enforced execution boundary.
  /init rix,
  /{,usr/}bin/{bash,dash,sh,env,with-contenv} rix,
  /usr/bin/{cat,chmod,chown,crontab,cut,date,find,grep,head,id,jq,ln,lsiown,mkdir,mv,pwdx,readlink,rm,sed,sleep,sort,stat,touch,tr,uname} rix,
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

  # Leave startup utilities behind when the actual server starts.
  "@{ghostship_plex_pms}/Plex Media Server" cx -> server,
  @{ghostship_plex_pms}/Resources/start.sh rix,
  # Only startup may modify scripts that startup can execute.
  /run/s6/ rw,
  /run/s6/** rwk,
  /run/service/ rw,
  /run/service/** rwk,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwk,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,
  signal (send, receive) peer=ghostship-plex,
  #include <plex-apparmor-runtime.inc>

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # The server and its helpers get no shell, downloader, or startup-tool execs.
    "@{ghostship_plex_pms}/Plex Media Server" rix,
    #include <plex-apparmor-runtime.inc>
  }
}
