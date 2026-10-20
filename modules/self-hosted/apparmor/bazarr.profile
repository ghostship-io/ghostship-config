# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer Bazarr v1.6.2-ls368 (lscr.io/linuxserver/bazarr:latest), Alpine 3.23
# (musl), Python 3.12 with the /lsiopy venv; s6-overlay 3.2.1.0;
# uid/gid 3000:3000 (LSIO_NON_ROOT_USER). Every process has CapEff=0: no
# capability rules. Config inspected (keys only): embedded subtitle detection
# uses ffprobe; post-processing, subsync and custom commands are disabled.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_bazarr_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_bazarr_app} = /app/bazarr/bin
@{ghostship_bazarr_site} = /lsiopy/lib/python3.12/site-packages

profile ghostship-bazarr flags=(complain,attach_disconnected,mediate_deleted) {
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
  @{ghostship_bazarr_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_bazarr_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_bazarr_s6}/etc/** r,
  @{ghostship_bazarr_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_bazarr_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-bazarr-config,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,svc-bazarr,svc-cron}/run rix,
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
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-bazarr}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-bazarr}/run rix,

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
  /usr/lib/lib{ncursesw.so.6.5,readline.so.8.3,acl.so.1.1.2302,attr.so.1.1.2502,crypto.so.3,skarnet.so.2.14.4.0,utmps.so.0.1.3.1} mr,

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

  # svc-bazarr: `s6-notifyoncheck -c "nc -z localhost 6767" ... cd /app/bazarr/bin
  # python3 /app/bazarr/bin/bazarr.py`; python3 resolves through /lsiopy/bin to
  # the system interpreter. The readiness string runs via execlineb, then nc.
  /usr/bin/python3.12 cx -> python,
  /usr/bin/nc cx -> readiness,

  # s6rc-oneshot-runner: s6-ipcserverd listens on a unix socket under
  # /run/service and s6-rc's s6-sudo clients connect to it. No IP sockets here:
  # wget (healthcheck) and nc (readiness) run in their own domains.
  network unix stream,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-bazarr,
  signal (send, receive) peer=ghostship-bazarr//python,
  signal (send, receive) peer=ghostship-bazarr//readiness,
  signal (send, receive) peer=ghostship-bazarr//tools,
  signal (send, receive) peer=ghostship-bazarr//ffprobe,
  signal (send, receive) peer=ghostship-bazarr//unrar,

  # Interpreter domain: bazarr.py (launcher) and its child bazarr/main.py, both
  # /usr/bin/python3.12. AppArmor cannot filter -c, imports or pickles; this
  # constrains effects only. No shell, pip, ffmpeg, or transition back to startup.
  profile python flags=(complain,attach_disconnected,mediate_deleted) {
    # The launcher re-executes sys.executable (/lsiopy/bin/python3) for main.py.
    /usr/bin/python3.12 rix,
    # ffprobe: embedded-subtitle track detection; unrar: rarfile's startup
    # tool probe and RAR subtitle archives from providers.
    /usr/bin/ffprobe px -> ghostship-bazarr//ffprobe,
    /usr/bin/unrar px -> ghostship-bazarr//unrar,

    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{bz2.so.1.0.8,lzma.so.5.8.4,python3.12.so.1.0,z.so.1.3.2,brotlicommon.so.1.2.0,brotlidec.so.1.2.0,cares.so.2.19.7,crypto.so.3,ssl.so.3,curl.so.4.8.0,expat.so.1.12.5,ffi.so.8.2.0} mr,
    /usr/lib/lib{gcc_s.so.1,idn2.so.0.4.0,mediainfo.so.0.2509.0,mpdec.so.4.0.1,nghttp2.so.14.29.4,psl.so.5.3.5,sqlite3.so.3.53.4,stdc++.so.6.0.34,tinyxml2.so.11.0.0,unistring.so.5.2.1,zen.so.0.4.41,zstd.so.1.5.7} mr,
    # Standard-library extension modules load lazily by import path; the
    # directory is image-owned (root, 0755). Python sources are read-only.
    /usr/lib/python3.12/ r,
    /usr/lib/python3.12/** r,
    /usr/lib/python3.12/lib-dynload/*.cpython-312-aarch64-linux-musl.so mr,
    # Venv (root-owned) and the native modules mapped by the live main.py.
    /lsiopy/ r,
    /lsiopy/** r,
    @{ghostship_bazarr_site}/lxml/{_elementpath,etree}.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_bazarr_site}/numpy/_core/_multiarray_umath.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_bazarr_site}/numpy/linalg/_umath_linalg.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_bazarr_site}/numpy.libs/{libgcc_s-2d945d6c-767fb991.so.1,libgcc_s-2d945d6c.so.1,libgfortran-67378ab2-e7e7cfab.so.5.0.0,libscipy_openblas64_-1fc386ee.so,libstdc++-85f2cd6d.so.6.0.33} mr,
    @{ghostship_bazarr_site}/PIL/_imaging.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_bazarr_site}/pillow.libs/{libbsd-6304e545.so.0.12.2,libjpeg-070e4618.so.62.4.0,liblzma-1c3b7648.so.5.8.3,libmd-e6555b27.so.0.1.0,libopenjp2-2adb8702.so.2.5.4,libtiff-29851ca2.so.6.2.0,libXau-541039f7.so.6.0.0,libxcb-b62355a5.so.1.1.0,libXdmcp-f7925934.so.6.0.0,libzstd-65db3951.so.1.5.7} mr,
    @{ghostship_bazarr_site}/psycopg2/_psycopg.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_bazarr_site}/psycopg2_binary.libs/{libcom_err-934f4c86.so.2.1,libcrypto-c0024b1a.so.3,libgssapi_krb5-bd701c95.so.2.2,libk5crypto-95e68b98.so.3.1,libkeyutils-6ce80ab8.so.1.10,libkrb5-46c15cab.so.3.3,libkrb5support-108576e7.so.0.1,liblber-3da4cb0c.so.2.0.200,libldap-a6923df4.so.2.0.200,libpq-845b2497.so.5.17,libsasl2-b0635103.so.3.0.0,libssl-a8271542.so.3} mr,
    # Bazarr sources and the bundled web frontend: read-only, root-owned.
    @{ghostship_bazarr_app}/ r,
    @{ghostship_bazarr_app}/** r,

    # State: config.yaml, SQLite db (with -shm/-wal), logs, backups, cache
    # (dogpile pickles: modifying them can execute Python on load), and the
    # launcher's STOPFILE/RESTARTFILE (/config/bazarr.{stop,restart}).
    /config/ rw,
    /config/** rwk,
    # Media libraries: read everything, write only subtitle sidecars.
    /tv/ r,
    /tv/** r,
    /tv/**.{srt,ass,ssa,sub,idx,vtt,smi,sup} rw,
    /movies/ r,
    /movies/** r,
    /movies/**.{srt,ass,ssa,sub,idx,vtt,smi,sup} rw,
    # tempfile.gettempdir(): rarfile spools in-memory archives here for unrar.
    /tmp/ r,
    /tmp/tmp* rw,

    / r,
    /{etc,usr,usr/lib,usr/share,dev,proc,sys}/ r,
    /etc/{passwd,group,hosts,resolv.conf,host.conf,nsswitch.conf,services,protocols,localtime,timezone,os-release,mime.types} r,
    /usr/lib/os-release r,
    /etc/ssl/ r,
    /etc/ssl/** r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdin,stdout,stderr} rw,
    /proc/{self,thread-self,[0-9]*}/{stat,status,statm,cmdline,mounts,mountinfo,cgroup} r,
    # subprocess closes inherited descriptors by listing /proc/self/fd.
    /proc/{self,thread-self,[0-9]*}/fd/ r,
    /proc/{cpuinfo,meminfo,stat} r,
    /sys/devices/system/cpu/{online,possible,present} r,

    # Web UI on 0.0.0.0/[::]:6767; Sonarr/Radarr APIs and subtitle providers;
    # DNS. AppArmor cannot restrict destinations or ports.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    signal (receive) peer=unconfined,
    signal (send, receive) peer=ghostship-bazarr,
    signal (send, receive) peer=ghostship-bazarr//python,
    signal (send, receive) peer=ghostship-bazarr//ffprobe,
    signal (send, receive) peer=ghostship-bazarr//unrar,
  }

  # Dynamic Alpine ffprobe: reads media only; no /config, no network.
  profile ffprobe flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/ffprobe rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{SPIRV-Tools-opt.so,SPIRV-Tools.so,SvtAv1Enc.so.3.1.2,X11-xcb.so.1.0.0,X11.so.6.4.0,Xau.so.6.0.0,Xdmcp.so.6.0.0,Xext.so.6.4.0,Xfixes.so.3.1.0,aom.so.3.14.1,asound.so.2.0.0,ass.so.9.4.1} mr,
    /usr/lib/lib{avcodec.so.62.11.100,avdevice.so.62.1.100,avfilter.so.11.4.100,avformat.so.62.3.100,avutil.so.60.8.100,bluray.so.3.0.0,brotlicommon.so.1.2.0,brotlidec.so.1.2.0,brotlienc.so.1.2.0,bsd.so.0.12.2,bz2.so.1.0.8,cjson.so.1.7.19} mr,
    /usr/lib/lib{crypto.so.3,dav1d.so.7.0.0,dbus-1.so.3.38.3,dovi.so.3.3.2,drm.so.2.131.0,expat.so.1.12.5,fontconfig.so.1.16.1,freetype.so.6.20.6,fribidi.so.0.4.0,gcc_s.so.1,glib-2.0.so.0.8600.3,glslang-default-resource-limits.so.15.4.0} mr,
    /usr/lib/lib{glslang.so.15.4.0,gomp.so.1.0.0,graphite2.so.3.2.1,harfbuzz.so.0.61220.0,hwy.so.1.3.0,intl.so.8.4.3,jpeg.so.8.3.2,jxl.so.0.11.2,jxl_cms.so.0.11.2,jxl_threads.so.0.11.2,lcms2.so.2.0.19,lilv-0.so.0.24.26} mr,
    /usr/lib/lib{lzma.so.5.8.4,mbedcrypto.so.3.6.7,md.so.0.1.0,mp3lame.so.0.0.0,mpg123.so.0.49.4,numa.so.1.0.0,ogg.so.0.8.6,openmpt.so.0.5.5,opus.so.0.10.1,pcre2-8.so.0.16.1,placebo.so.351,png16.so.16.59.0} mr,
    /usr/lib/lib{pulse.so.0.24.3,rav1e.so.0.8.1,rist.so.4.3.1,serd-0.so.0.32.4,shaderc_shared.so.1,sharpyuv.so.0.1.2,sodium.so.26.2.0,sord-0.so.0.16.18,soxr.so.0.1.2,sratom-0.so.0.6.18,srt.so.1.5.3,ssh.so.4.10.4} mr,
    /usr/lib/lib{ssl.so.3,stdc++.so.6.0.34,swresample.so.6.1.100,swscale.so.9.1.100,theoradec.so.2.1.1,theoraenc.so.2.2.1,udfread.so.3.0.0,unibreak.so.6.0.1,v4l2.so.0.0.0,v4lconvert.so.0.0.0,va-drm.so.2.2200.0,va-x11.so.2.2200.0} mr,
    /usr/lib/lib{va.so.2.2200.0,vdpau.so.1.0.0,vidstab.so.1.2,vorbis.so.0.4.9,vorbisenc.so.2.0.12,vorbisfile.so.3.3.8,vpx.so.11.0.1,vulkan.so.1.4.321,webp.so.7.2.0,webpmux.so.3.1.2,x264.so.164,x265.so.215} mr,
    /usr/lib/lib{xcb-dri3.so.0.1.0,xcb-shape.so.0.0.0,xcb-shm.so.0.0.0,xcb-xfixes.so.0.0.0,xcb.so.1.1.0,xml2.so.2.13.9,xvidcore.so.4.3,z.so.1.3.2,zimg.so.2.0.0,zix-0.so.0.6.2,zmq.so.5.2.5} mr,
    /usr/lib/pulseaudio/libpulsecommon-17.0.so mr,
    /tv/ r,
    /tv/** r,
    /movies/ r,
    /movies/** r,
    /dev/null rw,
    /proc/{self,thread-self}/{stat,status,maps} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-bazarr,
    signal (send, receive) peer=ghostship-bazarr//python,
    signal (send, receive) peer=ghostship-bazarr//ffprobe,
  }

  # Static unrar: lists/extracts RAR subtitle archives that rarfile spools to
  # /tmp and streams back over a pipe. No media, /config or network access.
  profile unrar flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/unrar rm,
    /tmp/ r,
    /tmp/tmp* r,
    /dev/null rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-bazarr,
    signal (send, receive) peer=ghostship-bazarr//python,
    signal (send, receive) peer=ghostship-bazarr//unrar,
  }

  # s6-notifyoncheck's `nc -z localhost 6767` until the web UI accepts.
  profile readiness flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/nc rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{bsd.so.0.12.2,md.so.0.1.0} mr,
    /etc/{hosts,resolv.conf,services} r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-bazarr,
    signal (send, receive) peer=ghostship-bazarr//readiness,
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
    signal (receive) peer=ghostship-bazarr,
    signal (send, receive) peer=ghostship-bazarr//tools,
  }
}
