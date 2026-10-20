# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/linuxserver/muximux:latest = 418923c8-ls139 (built 2022-10-22,
# deprecated upstream), Alpine musl 1.2.2, s6-overlay 3.1.0.1, nginx 1.18.0,
# PHP-FPM 7.4.26, git 2.30.6, BusyBox 1.32.1, GNU coreutils 8.32.
# Container user 0:3000 (root startup); PUID/PGID 3000 = abc. nginx and
# PHP-FPM masters run as root, their workers as abc.
# Mounts: /config (rw); /etc/cont-init.d/50-ghostship-writer and
# /run/ghostship/muximux-{patch-writer,save-config}.php (ro, Nix store).
# Muximux PHP code lives in the writable /config/www/muximux git checkout.
# Healthcheck: `sh -c "wget ... http://127.0.0.1/favicon.ico"` (BusyBox), and
# the collector's heartbeat runs `/bin/cat` (coreutils): both stay in the
# startup domain, which must keep BusyBox for its own scripts and crond.
# Load by name through the container runtime; there is no host attachment glob.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.

@{mx_s6} = /package/admin/s6-overlay-3.1.0.1
@{mx_www} = /config/www/muximux

profile ghostship-muximux flags=(complain,attach_disconnected,mediate_deleted) {
  # Startup, supervision and cron domain. Shell arguments and inline commands
  # cannot be filtered by AppArmor; read access lets bash interpret a file.
  /init rix,
  /docker-mods rix,
  /bin/bash rix,
  # BusyBox applets used by the scripts: sh, find, sed, xargs, crond,
  # run-parts, logger, which, and the healthcheck's wget.
  /bin/busybox rix,
  # coreutils multicall: ls, cat, id, date, uname, sleep, chown, chmod, mkdir,
  # cp, mv, rm, ln, wc, tr, head, tee, echo, test, env, basename.
  /usr/bin/coreutils rix,
  /usr/bin/{with-contenv,pwdx,pgrep} rix,
  /usr/sbin/{groupmod,usermod} rix,
  # 30-keygen: only when /config/keys has no certificate pair.
  /usr/bin/openssl rix,

  # Long-running servers, the startup PHP patch, git and logrotate each get
  # their own domain; none of them can transition back here.
  /usr/sbin/nginx cx -> nginx,
  /usr/sbin/php-fpm7 cx -> php,
  /usr/bin/php7 cx -> patcher,
  /usr/bin/git cx -> git,
  /usr/sbin/logrotate cx -> logrotate,

  # s6-overlay: exact version-pinned executables. execline commands are the
  # interpreter and chain-loading primitives of every s6 script.
  /package/admin/execline-2.8.3.0/command/{background,backtick,case,cd,define,dollarat,elgetopt,elgetpositionals,elglob,emptyenv,envfile,exec,execlineb,execline-cd,execline-umask,exit,export,fdblock,fdclose,fdmove,fdreserve,fdswap,forbacktickx,foreground,forstdin,forx,getcwd,getpid,heredoc,homeof,if,ifelse,ifte,ifthenelse,importas,loopwhilex,multidefine,multisubstitute,pipeline,piperw,posix-cd,posix-umask,redirfd,runblock,shift,trap,tryexec,umask,unexport,wait,withstdinas} rix,
  /package/admin/s6-2.11.1.0/command/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svok,s6-svstat,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-listen1,s6-ftrig-notify,s6-envdir,s6-envuidgid,s6-setuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcclient,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-sudo,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-fdholder-list,s6-fdholder-getdump,s6-fdholder-setdump,s6-fdholder-transferdump,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.3.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.0.7.3/command/{s6-linux-init,s6-linux-init-echo,s6-linux-init-hpr,s6-linux-init-maker,s6-linux-init-nuke,s6-linux-init-shutdown,s6-linux-init-shutdownd,s6-linux-init-umountall} rix,
  /package/admin/s6-portable-utils-2.2.4.0/command/{s6-cat,s6-chmod,s6-chown,s6-dumpenv,s6-echo,s6-hiercopy,s6-linkname,s6-ln,s6-ls,s6-mkdir,s6-rename,s6-rmrf,s6-sleep,s6-sort,s6-test} rix,
  /package/admin/s6-overlay-helpers-0.1.0.0/command/s6-overlay-suexec rix,
  @{mx_s6}/command/{with-contenv,printcontenv} rix,
  @{mx_s6}/libexec/{preinit,stage0} rix,
  @{mx_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{mx_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  @{mx_s6}/etc/** r,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/init-mods-package-install/run rix,
  /etc/cont-init.d/{01-envfile,10-adduser,20-config,30-keygen,40-install,50-ghostship-writer,99-custom-files,99-deprecation} rix,
  /etc/periodic/daily/logrotate rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot,shutdown} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner}/run rix,
  /run/s6/legacy-services/{cron,nginx,php-fpm}/run rix,

  # Loader and libraries of bash, coreutils, pwdx/pgrep and openssl. Resolved
  # SONAME targets only; version changes require review.
  /lib/ld-musl-aarch64.so.1 mr,
  /lib/lib{acl.so.1.1.2253,attr.so.1.1.2448,skarnet.so.2.10.0.0,utmps.so.0.1.0.0,procps.so.8.0.2,crypto.so.1.1,ssl.so.1.1} mr,
  /usr/lib/lib{ncursesw.so.6.2,readline.so.8.1,intl.so.8.1.7} mr,

  # s6 runtime trees. Startup owns the generated scripts above; no child
  # profile includes these paths.
  /run/ r,
  /run/s6/ rw,
  /run/s6/** rwkl,
  /run/service/ rw,
  /run/service/** rwkl,
  /run/s6-rc rwl,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwkl,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,
  /run/{crond.pid,crond.reboot} rw,

  # 10-adduser: groupmod/usermod rewrite the account databases with lock,
  # temporary and backup files.
  /etc/ r,
  /etc/{passwd,group,shadow,gshadow}{,-,+,.lock} rwl,
  /etc/{passwd,group,shadow,gshadow}.[0-9]* rwl,
  # 20-config: php-fpm configuration edits (BusyBox `sed -i` temp files) and
  # copies of the user overrides; logrotate.d permission reset.
  /etc/php7/ r,
  /etc/php7/php-fpm.conf{,??????} rw,
  /etc/php7/php-fpm.d/ r,
  /etc/php7/php-fpm.d/{www.conf,www.conf??????,www2.conf} rw,
  /etc/php7/conf.d/ r,
  /etc/php7/conf.d/php-local.ini rw,
  /etc/nginx/ r,
  /etc/nginx/conf.d rw,
  /etc/logrotate.d/ rw,
  /etc/logrotate.d/* rw,
  # docker-mods `chmod +x` the legacy scripts (chmod requires w). The
  # read-only Nix bind mount refuses the change for 50-ghostship-writer.
  /etc/cont-init.d/ rw,
  /etc/cont-init.d/* rw,
  /etc/services.d/ rw,
  /etc/services.d/** rw,
  /etc/crontabs/ r,
  /etc/crontabs/root r,
  /etc/periodic/ r,
  /etc/periodic/** r,

  # 10-adduser/20-config/40-install/50-ghostship-writer: `chown -R abc:abc
  # /config` and `chmod -R g+w /config/{nginx,www}` are unconditional, so
  # startup needs w (chown/chmod) across /config and directory reads to
  # recurse. Content reads are limited to the files the scripts copy.
  /config/ rw,
  /config/** w,
  /config/**/ r,
  /config/php/{php-local.ini,www2.conf} r,
  /config/nginx/nginx.conf r,
  /app/ rw,
  /defaults/ rw,
  /defaults/{nginx.conf,default,index.html} r,
  /var/lib/nginx/ rw,
  /var/lib/nginx/** rw,
  /var/tmp/nginx/ rw,
  /version.txt r,
  /{build_version,donate.txt} r,
  /custom-cont-init.d/ r,
  /custom-services.d/ r,

  /{usr,usr/lib,usr/share,dev,proc,sys}/ r,
  / r,
  /etc/{nsswitch.conf,hosts,hostname,resolv.conf,localtime,os-release,ssl/openssl.cnf} r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/urandom r,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  # nginx's run script: `pgrep -f`/`pkill` for stale nginx processes;
  # with-contenv's `pwdx $$` reads the shell's working directory.
  /proc/ r,
  /proc/[0-9]*/{cmdline,stat,status} r,
  ptrace (read) peer=ghostship-muximux,
  /proc/sys/kernel/{hostname,osrelease,ostype} r,
  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  # Root startup: s6-overlay-suexec/s6-applyuidgid, chown/chmod of abc files,
  # account database rewrites, signals to abc-owned processes.
  capability chown,
  capability fowner,
  capability dac_override,
  capability setuid,
  capability setgid,
  capability kill,

  # unix stream: s6-rc's oneshot runner and fdholder sockets.
  # unix dgram: crond -S and logger try syslog (/dev/log is absent).
  # inet stream: the healthcheck's wget to 127.0.0.1:80.
  network unix stream,
  network unix dgram,
  network inet stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-muximux,
  signal (send) peer=ghostship-muximux//{nginx,php,patcher,git,logrotate},

  profile nginx flags=(complain,attach_disconnected,mediate_deleted) {
    # Master (root) and workers (abc). No exec permissions at all.
    /usr/sbin/nginx mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/lib{crypto.so.1.1,ssl.so.1.1,z.so.1.2.12} mr,
    /usr/lib/libpcre.so.1.2.12 mr,
    /dev/zero rw,
    /dev/null rw,

    /config/nginx/ r,
    /config/nginx/nginx.conf r,
    /config/nginx/site-confs/ r,
    /config/nginx/site-confs/* r,
    /etc/nginx/ r,
    /etc/nginx/{mime.types,fastcgi_params} r,
    /etc/nginx/{http.d,modules}/ r,
    /config/keys/cert.{crt,key} r,
    /etc/ssl/openssl.cnf r,
    /etc/{passwd,group,localtime} r,
    /usr/share/zoneinfo/** r,

    /config/log/nginx/ r,
    /config/log/nginx/{access,error}.log w,
    /var/log/nginx/error.log w,
    /run/nginx.pid rw,
    /var/lib/nginx/ r,
    /var/lib/nginx/tmp/ rw,
    /var/lib/nginx/tmp/** rw,
    /var/tmp/nginx/ rw,
    /var/tmp/nginx/** rw,

    # Static assets only. The web root also holds settings backups,
    # secret.txt, muximux.log and .git; nginx has no reason to read them.
    @{mx_www}/ r,
    @{mx_www}/{css,fonts,images,js}/ r,
    @{mx_www}/{css,fonts,images,js}/** r,
    @{mx_www}/{favicon.ico,browserconfig.xml,manifest.json,robots.txt,romm-iframe-shim.js} r,

    # Master: bind :80/:443, chown temp paths, switch workers to abc, open
    # the abc-owned logs as root.
    capability net_bind_service,
    capability setuid,
    capability setgid,
    capability chown,
    capability dac_override,

    # TCP: listeners, fastcgi to 127.0.0.1:9000 and proxies to romm, grimmory,
    # pyload and uptime-kuma. UDP: the configured resolver (ipv6=off).
    # unix stream: master/worker channel socketpairs.
    network inet stream,
    network inet dgram,
    network unix stream,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux,
    signal (send, receive) peer=ghostship-muximux//nginx,
  }

  profile php flags=(complain,attach_disconnected,mediate_deleted) {
    # PHP-FPM master (root) and workers (abc) running the Muximux code.
    /usr/sbin/php-fpm7 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/lib{crypto.so.1.1,ssl.so.1.1,z.so.1.2.12} mr,
    /usr/lib/lib{argon2.so.1,edit.so.0.0.63,lzma.so.5.2.5,ncursesw.so.6.2,onig.so.5.1.0,pcre2-8.so.0.10.1,xml2.so.2.9.14} mr,
    /usr/lib/php7/modules/{fileinfo,json,mbstring,openssl,session,simplexml,xml,xmlwriter}.so mr,
    /dev/zero rw,
    /dev/null rw,
    # Every page render runs `which git`, `git --version` and
    # `git rev-parse` through popen's /bin/sh: a separate domain.
    /bin/busybox px -> ghostship-muximux//phpexec,

    /etc/php7/ r,
    /etc/php7/{php.ini,php-fpm.conf} r,
    /etc/php7/{conf.d,php-fpm.d}/ r,
    /etc/php7/conf.d/*.ini r,
    /etc/php7/php-fpm.d/*.conf r,
    /config/log/php/ r,
    /config/log/php/error.log rw,

    # Application code: read-only. It sits in a writable mount, so these
    # paths do not authenticate what PHP executes.
    @{mx_www}/ r,
    @{mx_www}/{index,login,muximux,combineify}.php r,
    @{mx_www}/vendor/ r,
    @{mx_www}/vendor/** r,
    @{mx_www}/{css,fonts,images,js}/ r,
    @{mx_www}/{css,fonts,images,js}/** r,
    # State: settings (with the Ghostship atomic writer's temp files), the
    # session secret, the app log, backups and the combineify cache.
    @{mx_www}/settings.ini.php-example r,
    @{mx_www}/settings.ini.php rwk,
    @{mx_www}/.muximux-config-* rwk,
    @{mx_www}/{secret.txt,muximux.log,backup.ini.php} rwk,
    @{mx_www}/cache/ rw,
    @{mx_www}/cache/** rwk,
    # PHP sessions (session.save_path is unset: /tmp).
    /tmp/ r,
    /tmp/sess_* rwk,

    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,localtime} r,
    /etc/ssl/{cert.pem,openssl.cnf} r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/** r,
    /usr/share/zoneinfo/** r,

    # Master: switch workers to abc and open the abc-owned log as root.
    capability setuid,
    capability setgid,
    capability dac_override,

    # TCP: the 127.0.0.1:9000 FastCGI listener and Muximux's GitHub branch
    # lookups over HTTPS; UDP for DNS.
    network inet stream,
    network inet dgram,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux,
    signal (send, receive) peer=ghostship-muximux//php,
  }

  # popen helpers from PHP: read-only git metadata queries. No network, no
  # writes: Muximux's self-update (git checkout/pull, zip download) is not
  # an allowed workload.
  profile phpexec flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /usr/bin/git rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/libz.so.1.2.12 mr,
    /usr/lib/libpcre2-8.so.0.10.1 mr,
    /dev/null rw,
    /etc/gitconfig r,
    /etc/{passwd,group} r,
    @{mx_www}/ r,
    @{mx_www}/.git/ r,
    @{mx_www}/.git/** r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux//php,
    signal (send, receive) peer=ghostship-muximux//phpexec,
  }

  # 50-ghostship-writer: the PHP CLI patches saveConfig into muximux.php.
  profile patcher flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/php7 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/lib{crypto.so.1.1,ssl.so.1.1,z.so.1.2.12} mr,
    /usr/lib/lib{argon2.so.1,edit.so.0.0.63,lzma.so.5.2.5,ncursesw.so.6.2,onig.so.5.1.0,pcre2-8.so.0.10.1,xml2.so.2.9.14} mr,
    /usr/lib/php7/modules/{fileinfo,json,mbstring,openssl,session,simplexml,xml,xmlwriter}.so mr,
    /dev/zero rw,
    /dev/null rw,
    /etc/php7/ r,
    /etc/php7/php.ini r,
    /etc/php7/conf.d/ r,
    /etc/php7/conf.d/*.ini r,
    /run/ghostship/ r,
    /run/ghostship/muximux-{patch-writer,save-config}.php r,
    @{mx_www}/muximux.php rwk,
    /etc/localtime r,
    /usr/share/zoneinfo/** r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux,
  }

  # 40-install: root `git checkout` of the pinned commit (git refuses the
  # abc-owned checkout as root). The conditional `git clone` is not allowed:
  # it would need network and git-remote-https.
  profile git flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/git mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/libz.so.1.2.12 mr,
    /usr/lib/libpcre2-8.so.0.10.1 mr,
    /dev/null rw,
    /etc/gitconfig r,
    /etc/{passwd,group} r,
    /root/.gitconfig r,
    /root/.config/git/config r,
    @{mx_www}/ r,
    @{mx_www}/.git/ r,
    @{mx_www}/.git/** r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux,
  }

  # Daily /etc/periodic/daily/logrotate from crond: rotates /config/log as abc
  # (`su abc abc`), gzip-compresses, and pokes s6 for nginx and php-fpm.
  profile logrotate flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/sbin/logrotate mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/libpopt.so.0.0.1 mr,
    # postrotate `sh -c` and the gzip compressor (BusyBox applets).
    /bin/busybox rix,
    /package/admin/s6-2.11.1.0/command/s6-svc rix,
    /dev/null rw,
    /etc/logrotate.conf r,
    /etc/logrotate.d/ r,
    /etc/logrotate.d/{acpid,nginx,php-fpm7} r,
    /etc/{passwd,group,localtime} r,
    /usr/share/zoneinfo/** r,
    /config/log/ r,
    /config/log/logrotate.status{,.tmp} rw,
    /config/log/{nginx,php}/ rw,
    /config/log/{nginx,php}/*.log{,.[0-9]*} rw,
    # s6-svc -h/-t writes the supervisors' control FIFOs.
    /run/s6/legacy-services/{nginx,php-fpm}/supervise/ r,
    /run/s6/legacy-services/{nginx,php-fpm}/supervise/control w,
    capability setuid,
    capability setgid,
    capability chown,
    capability fowner,
    capability dac_override,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-muximux,
    signal (send, receive) peer=ghostship-muximux//logrotate,
  }
}
