# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# LinuxServer pyLoad-ng 0.5.0b3.dev101-ls258 (lscr.io/linuxserver/pyload-ng:latest),
# Alpine 3.22.6 (musl), Python 3.12 in the /lsiopy venv; s6-overlay 3.2.1.0.
# s6 and the LinuxServer init run as root (CapEff 0x800405fb); the app runs
# as abc 3000:3000 (supplementary group 1000 "users") via s6-setuidgid.
# init-pyload-config/run and svc-pyload/run are read-only bind mounts from the
# Nix store; svc-pyload exports LD_PRELOAD=/lib/libgcompat.so.0 for its children.
# plugins.cfg: ExtractArchive (and so unrar/7z) is disabled; ExternalScripts is
# enabled but every /config/scripts/<event>/ directory is empty; YoutubeCom is
# enabled and may run ffmpeg to merge DASH streams. AntiVirus is disabled.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_pyload_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_pyload_py} = /usr/lib/python3.12
@{ghostship_pyload_site} = /lsiopy/lib/python3.12/site-packages
@{ghostship_pyload_dl} = /downloads/PyLoad

profile ghostship-pyload flags=(complain,attach_disconnected,mediate_deleted) {
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
  @{ghostship_pyload_s6}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{ghostship_pyload_s6}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{ghostship_pyload_s6}/etc/** r,
  @{ghostship_pyload_s6}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{ghostship_pyload_s6}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /etc/s6-overlay/ r,
  /etc/s6-overlay/s6-rc.d/ r,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-pyload-config,svc-cron,svc-pyload}/run rix,
  # S6_STAGE2_HOOK and the LinuxServer bash wrapper around /command/with-contenv.
  # /docker-mods would rewrite /usr/bin/with-contenv only if it were missing or
  # a symlink; it is a regular file here, so no write to it is allowlisted.
  /docker-mods rix,
  /usr/bin/with-contenv rix,
  # init-adduser/init-crontab-config/init-pyload-config ownership repair.
  /usr/bin/lsiown rix,

  # s6 generates these scripts in its writable runtime tree. These exact
  # startup/shutdown entrypoints are an intentional, limited code-loading risk;
  # never extend this to execution of /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  /run/s6/db/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-pyload}/run rix,
  /run/s6-rc:s6-rc-init:*/servicedirs/{s6rc-fdholder,s6rc-oneshot-runner,svc-cron,svc-pyload}/run rix,

  # Bash, the coreutils multicall (cat, cp, chown, mkdir, id, stat, tee, tr,
  # ...), findutils find (lsiown, init-envfile) and shadow's usermod/groupmod
  # (init-adduser re-ids abc to PUID/PGID 3000 on every start).
  /bin/bash rix,
  /bin/coreutils rix,
  /usr/bin/find rix,
  /usr/sbin/{usermod,groupmod} rix,
  # BusyBox is /init's and the healthcheck's /bin/sh interpreter (entered by
  # crun/podman exec, not by an exec rule). Applets exec'd by path (sed, grep,
  # awk, crontab, crond, wget, `busybox`) go to the tools domain instead.
  /bin/busybox mr,
  /bin/busybox cx -> tools,
  # s6-notifyoncheck's `nc -z localhost <webui port>` readiness probe.
  /usr/bin/nc cx -> readiness,
  # svc-pyload: `s6-setuidgid abc pyload --userdir /config`; PATH finds the
  # venv entry-point script, whose interpreter is /usr/bin/python3.12.
  /lsiopy/bin/pyload cx -> pyload,

  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/lib{ncursesw.so.6.5,readline.so.8.2,acl.so.1.1.2302,attr.so.1.1.2502,crypto.so.3,skarnet.so.2.14.4.0,utmps.so.0.1.3.1,bsd.so.0.12.2,md.so.0.1.0} mr,

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
  # (settings/accounts.cfg and plugins.cfg hold credentials): per-file getattr
  # records from this walk are expected during complain-mode review.
  /config/ rw,
  /config/**/ r,
  /app/ rw,
  /defaults/ rw,
  # init-pyload-config: mkdir -p, then cp -n the default config if missing.
  /config/settings/ rw,
  /config/settings/pyload.cfg rw,
  /defaults/pyload.cfg r,
  /downloads/ r,
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
  signal (send, receive) peer=ghostship-pyload,
  signal (send, receive) peer=ghostship-pyload//pyload,
  signal (send, receive) peer=ghostship-pyload//ffmpeg,
  signal (send, receive) peer=ghostship-pyload//readiness,
  signal (send, receive) peer=ghostship-pyload//tools,

  # pyLoad under the venv interpreter. Code (/lsiopy and the stdlib) is
  # root-owned and read-only to uid 3000. Its only exec is ffmpeg, in its own
  # domain: no ExternalScripts payloads, no extractors, no shell.
  profile pyload flags=(complain,attach_disconnected,mediate_deleted) {
    /lsiopy/bin/pyload r,
    /usr/bin/python3.12 rm,
    /usr/bin/ffmpeg px -> ghostship-pyload//ffmpeg,
    /lib/ld-musl-aarch64.so.1 mr,
    # LD_PRELOAD from svc-pyload/run and its two dependencies.
    /lib/libgcompat.so.0 mr,
    /usr/lib/lib{ucontext.so.1,obstack.so.1.0.0} mr,
    /usr/lib/lib{python3.12.so.1.0,bz2.so.1.0.8,crypto.so.3,ssl.so.3,ffi.so.8.1.4,lzma.so.5.8.4,mpdec.so.4.0.1,sqlite3.so.3.49.2,z.so.1.3.2,zstd.so.1.5.7} mr,
    # pycurl's libcurl and its resolver/IDN/compression dependencies.
    /usr/lib/lib{curl.so.4.8.0,cares.so.2.19.7,brotlicommon.so.1.1.0,brotlidec.so.1.1.0,idn2.so.0.4.0,nghttp2.so.14.29.4,psl.so.5.3.5,unistring.so.5.2.0} mr,
    # Exact stdlib and venv extension modules mapped by the live process.
    @{ghostship_pyload_py}/lib-dynload/{array,_asyncio,binascii,_bisect,_blake2,_bz2,_contextvars,_csv,_ctypes,_datetime,_decimal,fcntl,grp,_hashlib,_heapq,_json,_lzma,math,_opcode,_pickle,_posixsubprocess,_queue,_random,select,_sha2,_socket,_sqlite3,_ssl,_struct,unicodedata,zlib,_zoneinfo}.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/{_brotli,_cffi_backend}.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/backports/zstd/_zstd.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/cryptography/hazmat/bindings/_rust.abi3.so mr,
    @{ghostship_pyload_site}/cryptography.libs/libgcc_s-2d945d6c.so.1 mr,
    @{ghostship_pyload_site}/markupsafe/_speedups.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/msgspec/_core.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/pycurl/_pycurl.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/pydantic_core/_pydantic_core.cpython-312-aarch64-linux-musl.so mr,
    @{ghostship_pyload_site}/pydantic_core.libs/libgcc_s-0bf60adc.so.1 mr,

    @{ghostship_pyload_py}/ r,
    @{ghostship_pyload_py}/** r,
    /lsiopy/ r,
    /lsiopy/** r,

    # --userdir /config: settings (incl. account credentials), data/pyload.db,
    # flask sessions, logs. /config/plugins and /config/scripts are writable
    # here and pyLoad imports/executes from them: see the profile review notes.
    /config/ rw,
    /config/** rwk,
    # storage_folder is forced to /downloads/PyLoad by init-pyload-config.
    /downloads/ r,
    @{ghostship_pyload_dl}/ rw,
    @{ghostship_pyload_dl}/** rwk,
    /tmp/ r,
    /tmp/pyLoad/ rw,
    /tmp/pyLoad/** rwk,

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

    # Web UI on 0.0.0.0:8000 and hoster downloads over HTTP(S); musl and c-ares
    # DNS over UDP. AppArmor cannot restrict destinations or ports.
    network inet stream,
    network inet dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-pyload,
    signal (send, receive) peer=ghostship-pyload//pyload,
    signal (send, receive) peer=ghostship-pyload//ffmpeg,
  }

  # YoutubeCom's ffmpeg: merge downloaded audio/video streams in the download
  # folder. No /config, no network (inputs are already-downloaded local files),
  # no further execs. The inherited LD_PRELOAD maps gcompat here too.
  profile ffmpeg flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/ffmpeg rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/libgcompat.so.0 mr,
    /usr/lib/lib{ucontext.so.1,obstack.so.1.0.0} mr,
    /usr/lib/lib{aom.so.3.12.1,asound.so.2.0.0,ass.so.9.3.1,asyncns.so.0.3.1,avcodec.so.60.31.102,avdevice.so.60.3.100,avfilter.so.9.12.100,avformat.so.60.16.100,avutil.so.58.29.100,bluray.so.2.4.3,brotlicommon.so.1.1.0,brotlidec.so.1.1.0,brotlienc.so.1.1.0,bsd.so.0.12.2,bz2.so.1.0.8,cjson.so.1.7.19,crypto.so.3,dav1d.so.7.0.0,dbus-1.so.3.38.3,dovi.so.3.3.1,drm.so.2.124.0,expat.so.1.12.5,FLAC.so.12.1.0,fontconfig.so.1.12.1,freetype.so.6.20.2,fribidi.so.0.4.0,gcc_s.so.1,glib-2.0.so.0.8400.4} mr,
    /usr/lib/lib{glslang-default-resource-limits.so.15.2.0,glslang.so.15.2.0,gomp.so.1.0.0,graphite2.so.3.2.1,harfbuzz.so.0.61121.0,hwy.so.1.0.7,intl.so.8.4.3,jpeg.so.8.3.2,jxl_cms.so.0.10.3,jxl.so.0.10.3,jxl_threads.so.0.10.3,lcms2.so.2.0.19,lilv-0.so.0.24.26,lzma.so.5.8.4,mbedcrypto.so.3.6.7,md.so.0.1.0,mp3lame.so.0.0.0,mpg123.so.0.48.3,numa.so.1.0.0,ogg.so.0.8.5,openmpt.so.0.4.4,opus.so.0.10.1,pcre2-8.so.0.14.0,placebo.so.338,png16.so.16.59.0,postproc.so.57.3.100,pulse.so.0.24.3,rav1e.so.0.7.1,rist.so.4.3.1} mr,
    /usr/lib/lib{SDL2-2.0.so.0.3200.56,serd-0.so.0.32.4,shaderc_shared.so.1,sharpyuv.so.0.1.1,sndfile.so.1.0.37,sodium.so.26.2.0,sord-0.so.0.16.18,soxr.so.0.1.2,SPIRV-Tools-opt.so,SPIRV-Tools.so,sratom-0.so.0.6.18,srt.so.1.5.3,ssh.so.4.10.2,ssl.so.3,stdc++.so.6.0.33,SvtAv1Enc.so.2.3.0,swresample.so.4.12.100,swscale.so.7.5.100,theoradec.so.1.1.4,theoraenc.so.1.1.2,unibreak.so.6.0.1,v4l2.so.0.0.0,v4lconvert.so.0.0.0} mr,
    /usr/lib/lib{va-drm.so.2.2200.0,va.so.2.2200.0,va-x11.so.2.2200.0,vdpau.so.1.0.0,vidstab.so.1.2,vorbisenc.so.2.0.12,vorbisfile.so.3.3.8,vorbis.so.0.4.9,vpx.so.9.1.0,vulkan.so.1.4.313,webpmux.so.3.1.1,webp.so.7.1.10,X11.so.6.4.0,X11-xcb.so.1.0.0,x264.so.164,x265.so.209,Xau.so.6.0.0,xcb-dri3.so.0.1.0,xcb-shape.so.0.0.0,xcb-shm.so.0.0.0,xcb.so.1.1.0,xcb-xfixes.so.0.0.0,Xdmcp.so.6.0.0,Xext.so.6.4.0,Xfixes.so.3.1.0,xml2.so.2.13.9,xvidcore.so.4.3,zimg.so.2.0.0,zix-0.so.0.6.2,zmq.so.5.2.5,z.so.1.3.2} mr,
    /usr/lib/pulseaudio/libpulsecommon-17.0.so mr,
    /downloads/ r,
    @{ghostship_pyload_dl}/ r,
    @{ghostship_pyload_dl}/** rw,
    /etc/{passwd,group,localtime} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-pyload,
    signal (receive) peer=ghostship-pyload//pyload,
    signal (send, receive) peer=ghostship-pyload//ffmpeg,
  }

  # netcat-openbsd readiness probe to loopback, up to 300 tries 1 s apart.
  # It inherits svc-pyload's LD_PRELOAD.
  profile readiness flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/nc rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /lib/libgcompat.so.0 mr,
    /usr/lib/lib{ucontext.so.1,obstack.so.1.0.0,bsd.so.0.12.2,md.so.0.1.0} mr,
    /etc/{hosts,resolv.conf,services} r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-pyload,
    signal (send, receive) peer=ghostship-pyload//readiness,
  }

  # BusyBox applets exec'd by path, all as root: /docker-mods' grep of
  # /proc/mounts; init-pyload-config's `sed -i` on pyload.cfg (keeps the owner,
  # hence chown); svc-pyload's sed|grep|awk port lookup; crontab import and
  # probes; the resident crond (setuid/setgid to run jobs) and its
  # `sh -c run-parts /etc/periodic/*` (all five directories are empty); the
  # podman healthcheck's wget to loopback. AppArmor cannot select applets by
  # argv, so this domain also covers sh. No other /config access, no app tree.
  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    capability chown,
    capability setuid,
    capability setgid,
    /config/settings/ r,
    /config/settings/pyload.cfg rw,
    /config/settings/pyload.cfg?????? rw,
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
    signal (receive) peer=ghostship-pyload,
    signal (send, receive) peer=ghostship-pyload//tools,
  }
}
