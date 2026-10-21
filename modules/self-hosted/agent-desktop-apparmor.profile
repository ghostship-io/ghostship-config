# Agent Desktop container policy: a strict allowlist per daemon class, plus
# the confined desktop viewer below (left unchanged).
#
# Inspected on chill-penguin (aarch64), 2026-10-20, read-only (process tree,
# maps, fds, sockets and the image filesystem through /proc/<pid>/root):
#   image  localhost/ghostship-agent-desktop (webtop ubuntu-lxqt
#          sha256:92db2b409b2d72914d93fec49f0f96d6da9bb9a497d1dd51d1ca9df4cedf94ac,
#          Ubuntu 26.04.1), Google Chrome 155.0.8059.39-1, Bladebro 4.6.4,
#          s6-overlay 3.2.1.0, Python 3.14, sway/wlroots 0.19, OpenSSH 10.
#   users  s6, startup, nginx master and sshd run as root (the container's
#          bounding set: chown dac_override fowner fsetid kill setgid setuid
#          setpcap net_bind_service sys_chroot setfcap); everything else runs
#          as abc (uid/gid 3000); nginx workers as www-data.
#
# Every profile is in complain mode while learning. Keep complain until daily
# review records seven observed days without changes; a policy change
# restarts that window.
#
# Conventions:
#   - No abstractions in these profiles: their implicit permissions would
#     obscure the allowlist. The viewer profile below predates this and keeps
#     its own abstraction and tunables (hence the include).
#   - Exact executables and libraries (resolved real paths). Globs only for
#     plugin directories, Python stdlib/extension trees, pids and the data
#     trees each daemon manages.
#   - The only explicit deny rules are Podman's baseline in the top profile
#     (they enforce even in complain mode). The viewer keeps its own denies.
#   - Nothing here names a container IP: the agent-desktop update canaries
#     (agent-desktop-update.py) run lab containers under this same profile
#     on a different address.
#   - D-Bus rules are omitted: /sys/kernel/security is not mounted in the
#     container, so the bus daemons cannot mediate.
#
# Live children while the desktop runs: nginx, sshd, dbus-system, pulseaudio,
# selkies, pelorus, desktop, api, chrome-control. On demand: chrome-agent-
# launcher, chrome-personal-launcher, chrome-agent, chrome-personal, sway,
# stage-control (while an identity's Chrome is wanted up); agent-shell, bladebro,
# sudo, chrome-instance-launcher, chrome-other (SSH sessions, extra instances,
# a person's Chrome on the desktop); healthcheck (every 30 s).
include <tunables/global>

@{gs_lib} = /usr/lib/aarch64-linux-gnu
@{gs_ld} = /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1
@{gs_cu} = /usr/lib/cargo/bin/coreutils
@{gs_s6} = /package/admin/s6-2.13.2.0/command
@{gs_s6o} = /package/admin/s6-overlay-3.2.1.0
@{gs_tools} = /opt/ghostship-agent-desktop
@{gs_data} = /config/agent-desktop
@{gs_xdg} = /config/.XDG
# s6-rc's compiled service directories (the resolved /run/service/<svc>).
@{gs_svcdirs} = /run/s6-rc:s6-rc-init:*/servicedirs /run/s6/db/servicedirs
# Any browser profile name except the two identities: extra instances and a
# person's desktop Chrome must not open the agent or personal profile.
@{gs_other} = {[^ap]*,a,a[^g]*,ag,ag[^e]*,age,age[^n]*,agen,agen[^t]*,agent?*,p,p[^e]*,pe,pe[^r]*,per,per[^s]*,pers,pers[^o]*,perso,perso[^n]*,person,person[^a]*,persona,persona[^l]*,personal?*}

# Libraries each class mapped on the inspected image (resolved filenames).
@{gs_libs_chrome} = @{gs_lib}/{libEGL.so.1.1.0,libEGL_mesa.so.0.0.0,libFLAC.so.14.0.0,libGLX.so.0.0.0,libGLdispatch.so.0.0.0,libLLVM.so.21.1,libOpenGL.so.0.0.0,libQt6Core.so.6.10.2,libQt6DBus.so.6.10.2,libQt6Gui.so.6.10.2,libQt6Svg.so.6.10.2,libQt6WaylandClient.so.6.10.2,libQt6Widgets.so.6.10.2,libQt6XdgIconLoader.so.4.3.0,libX11-xcb.so.1.0.0,libX11.so.6.4.0,libXRes.so.1.0.0,libXau.so.6.0.0,libXcomposite.so.1.0.0,libXcursor.so.1.0.2,libXdamage.so.1.1.0,libXdmcp.so.6.0.0,libXext.so.6.4.0,libXfixes.so.3.1.0,libXi.so.6.1.0,libXinerama.so.1.0.0,libXrandr.so.2.2.0,libXrender.so.1.3.0,libapparmor.so.1.30.7,libasound.so.2.0.0,libasyncns.so.0.3.1,libatk-1.0.so.0.26013.1,libatk-bridge-2.0.so.0.0.0,libatomic.so.1.2.0,libatspi.so.0.0.1,libavahi-client.so.3.2.9,libavahi-common.so.3.5.4,libb2.so.1.0.4,libblkid.so.1.1.0,libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libbsd.so.0.12.2,libbz2.so.1.0.4,libc.so.6,libcairo-gobject.so.2.11804.4,libcairo.so.2.11804.4,libcom_err.so.2.1,libcups.so.2,libdatrie.so.1.4.1,libdbus-1.so.3.38.3,libdbusmenu-lxqt.so.0.3.0,libdl.so.2,libdouble-conversion.so.3.1,libdrm.so.2.131.0,libdrm_amdgpu.so.1.131.0,libedit.so.2.0.76,libelf-0.194.so,libepoxy.so.0.0.0,libexpat.so.1.11.2,libffi.so.8.2.0,libfontconfig.so.1.16.1,libfreeblpriv3.so,libfreetype.so.6.20.5,libfribidi.so.0.4.0,libgallium-26.0.8-1ubuntu0.3.so,libgbm.so.1.0.0,libgcc_s.so.1,libgdk-3.so.0.2420.32,libgdk_pixbuf-2.0.so.0.4400.5,libgio-2.0.so.0.8800.0,libglib-2.0.so.0.8800.0,libglycin-2.so.0,libgmodule-2.0.so.0.8800.0,libgmp.so.10.5.0,libgnutls.so.30.41.1,libgobject-2.0.so.0.8800.0,libgomp.so.1.0.0,libgraphite2.so.3.2.1,libgssapi_krb5.so.2.2,libgtk-3.so.0.2420.32,libharfbuzz.so.0.61232.0,libhogweed.so.6.11,libicudata.so.78.2,libicui18n.so.78.2,libicuuc.so.78.2,libidn2.so.0.4.0,libk5crypto.so.3.1,libkeyutils.so.1.10,libkrb5.so.3.3,libkrb5support.so.0.1,liblcms2.so.2.0.17,libm.so.6,libmd.so.0.1.0,libmd4c.so.0.5.2,libmount.so.1.1.0,libmp3lame.so.0.0.0,libmpg123.so.0.49.4,libmvec.so.1,libnettle.so.8.11,libnspr4.so,libnss3.so,libnssckbi.so,libnssutil3.so,libogg.so.0.8.6,libopus.so.0.11.1,libp11-kit.so.0.4.8,libpango-1.0.so.0.5700.0,libpangocairo-1.0.so.0.5700.0,libpangoft2-1.0.so.0.5700.0,libpcre2-16.so.0.14.0,libpcre2-8.so.0.14.0,libpixman-1.so.0.46.4,libplc4.so,libplds4.so,libpng16.so.16.57.0,libpthread.so.0,libpulse.so.0.24.3,libresolv.so.2,libseccomp.so.2.6.0,libselinux.so.1,libsensors.so.5.0.0,libsmime3.so,libsndfile.so.1.0.37,libsoftokn3.so,libsqlite3.so.0.8.6,libstdc++.so.6.0.35,libsystemd.so.0.42.0,libtasn1.so.6.6.5,libthai.so.0.3.2,libtinfo.so.6.6,libudev.so.1.7.12,libunistring.so.5.2.0,libva-drm.so.2.2300.0,libva.so.2.2300.0,libvorbis.so.0.4.9,libvorbisenc.so.2.0.12,libwayland-client.so.0.24.0,libwayland-cursor.so.0.24.0,libwayland-egl.so.1.24.0,libxcb-dri3.so.0.1.0,libxcb-present.so.0.0.0,libxcb-randr.so.0.1.0,libxcb-render.so.0.0.0,libxcb-shm.so.0.0.0,libxcb-sync.so.1.0.0,libxcb-xfixes.so.0.0.0,libxcb.so.1.1.0,libxkbcommon.so.0.13.1,libxml2.so.16.1.2,libxshmfence.so.1.0.0,libz.so.1.3.1,libzstd.so.1.5.7}
@{gs_libs_sway} = @{gs_lib}/{libEGL.so.1.1.0,libEGL_mesa.so.0.0.0,libGLESv2.so.2.1.0,libGLdispatch.so.0.0.0,libLLVM.so.21.1,libX11-xcb.so.1.0.0,libX11.so.6.4.0,libXau.so.6.0.0,libXdmcp.so.6.0.0,libXext.so.6.4.0,libXrender.so.1.3.0,libatomic.so.1.2.0,libblkid.so.1.1.0,libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libbsd.so.0.12.2,libbz2.so.1.0.4,libc.so.6,libcairo.so.2.11804.4,libdatrie.so.1.4.1,libdisplay-info.so.0.3.0,libdrm.so.2.131.0,libdrm_amdgpu.so.1.131.0,libedit.so.2.0.76,libelf-0.194.so,libevdev.so.2.3.0,libexpat.so.1.11.2,libffi.so.8.2.0,libfontconfig.so.1.16.1,libfreetype.so.6.20.5,libfribidi.so.0.4.0,libgallium-26.0.8-1ubuntu0.3.so,libgbm.so.1.0.0,libgcc_s.so.1,libgdk_pixbuf-2.0.so.0.4400.5,libgio-2.0.so.0.8800.0,libglib-2.0.so.0.8800.0,libglycin-2.so.0,libgmodule-2.0.so.0.8800.0,libgobject-2.0.so.0.8800.0,libgraphite2.so.3.2.1,libgudev-1.0.so.0.3.0,libharfbuzz.so.0.61232.0,libinput.so.10.13.0,libjson-c.so.5.4.0,liblcms2.so.2.0.17,libliftoff.so.0.5.0,libm.so.6,libmd.so.0.1.0,libmount.so.1.1.0,libmtdev.so.1.0.0,libpango-1.0.so.0.5700.0,libpangocairo-1.0.so.0.5700.0,libpangoft2-1.0.so.0.5700.0,libpcre2-8.so.0.14.0,libpixman-1.so.0.46.4,libpng16.so.16.57.0,libseat.so.1,libseccomp.so.2.6.0,libselinux.so.1,libsensors.so.5.0.0,libstdc++.so.6.0.35,libsystemd.so.0.42.0,libthai.so.0.3.2,libtinfo.so.6.6,libudev.so.1.7.12,libvulkan.so.1.4.341,libwacom.so.9.0.0,libwayland-client.so.0.24.0,libwayland-server.so.0.24.0,libwlroots-0.19.so,libxcb-composite.so.0.0.0,libxcb-dri3.so.0.1.0,libxcb-errors.so.0.0.0,libxcb-ewmh.so.2.0.0,libxcb-icccm.so.4.0.0,libxcb-present.so.0.0.0,libxcb-randr.so.0.1.0,libxcb-render-util.so.0.0.0,libxcb-render.so.0.0.0,libxcb-res.so.0.0.0,libxcb-shm.so.0.0.0,libxcb-sync.so.1.0.0,libxcb-xfixes.so.0.0.0,libxcb-xinput.so.0.1.0,libxcb.so.1.1.0,libxkbcommon.so.0.13.1,libxml2.so.16.1.2,libxshmfence.so.1.0.0,libz.so.1.3.1,libzstd.so.1.5.7}
@{gs_libs_python} = @{gs_lib}/{libc.so.6,libm.so.6,libexpat.so.1.11.2,libz.so.1.3.1,libbz2.so.1.0.4,liblzma.so.5.8.3,libzstd.so.1.5.7,libcrypto.so.3,libssl.so.3,libffi.so.8.2.0,libuuid.so.1.3.0,libsqlite3.so.0.8.6}
@{gs_libs_curl} = @{gs_lib}/{libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libc.so.6,libcom_err.so.2.1,libcrypto.so.3,libcurl.so.4.8.0,libffi.so.8.2.0,libgmp.so.10.5.0,libgnutls.so.30.41.1,libgssapi_krb5.so.2.2,libhogweed.so.6.11,libidn2.so.0.4.0,libk5crypto.so.3.1,libkeyutils.so.1.10,libkrb5.so.3.3,libkrb5support.so.0.1,liblber.so.2.0.200,libldap.so.2.0.200,libnettle.so.8.11,libnghttp2.so.14.29.2,libp11-kit.so.0.4.8,libpsl.so.5.3.4,libresolv.so.2,librtmp.so.1,libsasl2.so.2.0.25,libssh2.so.1.0.1,libssl.so.3,libtasn1.so.6.6.5,libunistring.so.5.2.0,libz.so.1.3.1,libzstd.so.1.5.7}
# bash, dash, util-linux, procps, GNU and Rust coreutils, grep, sed, mawk.
@{gs_libs_shell} = @{gs_lib}/{libc.so.6,libm.so.6,libgcc_s.so.1,libtinfo.so.6.6,libpcre2-8.so.0.14.0,libselinux.so.1,libsystemd.so.0.42.0,libacl.so.1.1.2302,libattr.so.1.1.2502,libproc2.so.0.0.2}
@{gs_libs_pactl} = @{gs_lib}/{libFLAC.so.14.0.0,libX11-xcb.so.1.0.0,libX11.so.6.4.0,libXau.so.6.0.0,libXdmcp.so.6.0.0,libapparmor.so.1.30.7,libasyncns.so.0.3.1,libdbus-1.so.3.38.3,libmp3lame.so.0.0.0,libmpg123.so.0.49.4,libmvec.so.1,libogg.so.0.8.6,libopus.so.0.11.1,libpulse.so.0.24.3,libsndfile.so.1.0.37,libvorbis.so.0.4.9,libvorbisenc.so.2.0.12,libxcb.so.1.1.0,pulseaudio/libpulsecommon-17.0.so}
# The shell utilities the scripts call (resolved; Rust coreutils multicall dir).
@{gs_cu_cmds} = @{gs_cu}/{basename,cat,chmod,chown,cut,date,dirname,env,false,head,id,install,ln,ls,mkdir,mktemp,nice,nohup,printf,readlink,realpath,seq,sleep,sort,stat,tail,timeout,touch,tr,tty,uname,wc}

profile ghostship-agent-desktop flags=(complain,attach_disconnected,mediate_deleted) {
  # Startup domain: s6-overlay, the LinuxServer webtop oneshots, our cont-init
  # script, the longrun run scripts up to their daemon exec, cont-finish, the
  # host's `podman exec chrome-stop-all` pre-stop, Podman's healthcheck shell,
  # and chrome-ensure when the viewer starts an idle-stopped Chrome. Each
  # daemon enters its own child at exec; nothing transitions back here.
  # Shell arguments cannot be filtered: every allowed shell runs only image
  # scripts listed below.

  capability chown,
  capability dac_override,
  capability fowner,
  capability fsetid,
  capability kill,
  capability setgid,
  capability setuid,

  network unix stream,
  network unix dgram,

  signal (receive) peer=unconfined,
  signal (send,receive) peer=ghostship-agent-desktop,
  signal (send) peer=ghostship-agent-desktop//*,
  signal (receive) peer=ghostship-agent-desktop//*,
  signal (send) peer=ghostship-desktop-viewer,
  signal (receive) peer=ghostship-desktop-viewer,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}runc,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}crun*,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}podman,

  # Podman's default container policy (container-default-apparmor.profile).
  deny @{PROC}/* w,
  deny @{PROC}/{[^1-9],[^1-9][^0-9],[^1-9s][^0-9y][^0-9s],[^1-9][^0-9][^0-9][^0-9]*}/** w,
  deny @{PROC}/sys/[^k]** w,
  deny @{PROC}/sys/kernel/{?,??,[^s][^h][^m]**} w,
  deny @{PROC}/sysrq-trigger rwklx,
  deny @{PROC}/kcore rwklx,

  deny mount,

  deny /sys/[^f]*/** wklx,
  deny /sys/f[^s]*/** wklx,
  deny /sys/fs/[^c]*/** wklx,
  deny /sys/fs/c[^g]*/** wklx,
  deny /sys/fs/cg[^r]*/** wklx,
  deny /sys/firmware/** rwklx,
  deny /sys/kernel/security/** rwklx,

  ptrace (trace,read) peer=ghostship-agent-desktop,
  ptrace (read) peer=ghostship-desktop-viewer,

  # The viewer's s6 run script enters its profile on exec.
  change_profile -> ghostship-desktop-viewer,
  /proc/[0-9]*/attr/{apparmor/,}exec w,

  # --- s6-overlay (same pinned versions as the Plex policy) ---
  /init rix,
  /package/admin/execline-2.9.7.0/command/execline rix,
  /package/admin/s6-portable-utils-2.3.1.0/command/s6-portable-utils rix,
  /package/admin/s6-linux-utils-2.6.3.0/command/s6-linux-utils rix,
  /package/admin/s6-overlay-helpers-0.1.2.0/command/{s6-overlay-stat,s6-overlay-suexec} rix,
  @{gs_s6}/{s6-svscan,s6-supervise,s6-svscanctl,s6-svc,s6-svperms,s6-svstat,s6-svok,s6-svwait,s6-svlisten1,s6-ftrigrd,s6-ftrig-notify,s6-envdir,s6-setuidgid,s6-envuidgid,s6-applyuidgid,s6-notifyoncheck,s6-ipcserver-socketbinder,s6-ipcserverd,s6-ipcserver-access,s6-ipcclient,s6-sudoc,s6-sudod,s6-fdholderd,s6-fdholder-daemon,s6-fdholder-store,s6-fdholder-retrieve,s6-fdholder-delete,s6-setsid,s6-log,s6-tai64n} rix,
  /package/admin/s6-rc-0.5.6.0/command/{s6-rc,s6-rc-init,s6-rc-compile,s6-rc-db,s6-rc-oneshot-run,s6-rc-fdholder-filler} rix,
  /package/admin/s6-linux-init-1.1.3.0/command/{s6-linux-init,s6-linux-init-maker,s6-linux-init-shutdownd,s6-linux-init-hpr,s6-linux-init-nuke,s6-linux-init-umountall} rix,
  @{gs_s6o}/command/{with-contenv,printcontenv,logutil-service,logutil-newfifo} rix,
  @{gs_s6o}/libexec/{preinit,stage0,fix-attrs,logutil-service-main} rix,
  @{gs_s6o}/etc/** r,
  @{gs_s6o}/etc/s6-rc/scripts/{cont-init,cont-finish,fix-attrs,services-up,services-down} rix,
  @{gs_s6o}/etc/s6-linux-init/skel/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /usr/bin/with-contenv rix,
  /etc/s6-overlay/s6-rc.d/** r,
  /etc/s6-overlay/s6-rc.d/{init-adduser,init-crontab-config,init-custom-files,init-device-perms,init-envfile,init-migrations,init-mods-package-install,init-nginx,init-selkies-config,init-video}/run rix,
  # s6 generates these in its root-owned runtime tree: an intentional,
  # limited code-loading risk. Never extend it to /run/**, /tmp/** or /config/**.
  /run/s6/basedir/bin/{init,halt,poweroff,reboot} rix,
  /run/s6/basedir/scripts/{rc.init,rc.shutdown,rc.shutdown.final} rix,
  /run/{service,s6/basedir/run-image/service}/.s6-svscan/{SIGINT,SIGPWR,SIGQUIT,SIGTERM,SIGUSR1,SIGUSR2,SIGWINCH,crash,finish} rix,
  /run/{service,s6/basedir/run-image/service}/s6-linux-init-shutdownd/run rix,
  @{gs_svcdirs}/{s6rc-fdholder,s6rc-oneshot-runner,svc-agent-desktop-api,svc-agent-desktop-apps,svc-agent-desktop-chrome-idle,svc-agent-desktop-sshd,svc-agent-desktop-viewer,svc-cron,svc-dbus,svc-de,svc-docker,svc-nginx,svc-pulseaudio,svc-selkies,svc-watchdog,svc-xorg,svc-xsettingsd}/run rix,
  # Each identity's Chrome service enters its own launcher, so the agent
  # and personal browsers never share a profile domain.
  @{gs_svcdirs}/svc-agent-desktop-chrome-agent/run cx -> chrome-agent-launcher,
  @{gs_svcdirs}/svc-agent-desktop-chrome-personal/run cx -> chrome-personal-launcher,
  /etc/cont-finish.d/ r,
  /etc/cont-finish.d/00-chrome-stop rix,
  /custom-cont-init.d/ r,
  /custom-cont-init.d/00-agent-desktop-init r,

  # --- Shells and utilities the startup scripts call ---
  /usr/bin/{bash,dash} rix,
  @{gs_cu_cmds} rix,
  /usr/bin/{diff,find,flock,getent,gnucp,gnumv,gnurm,gnutrue,grep,kill,lsiown,mawk,pgrep,pwdx,sed,setsid,which.debianutils,xargs} rix,
  /usr/sbin/{groupadd,groupmod,usermod} rix,
  /usr/bin/{openssl,ssh-keygen,pactl} rix,
  @{gs_tools}/{chrome-ensure,chrome-stop-all} rix,
  @{gs_ld} mr,
  @{gs_libs_shell} mr,
  @{gs_lib}/{libcrypto.so.3,libssl.so.3,libz.so.1.3.1,libzstd.so.1.5.7,libaudit.so.1.0.0,libbz2.so.1.0.4,libcap-ng.so.0.0.0,libsemanage.so.2,libsepol.so.2} mr,
  @{gs_libs_pactl} mr,
  @{gs_lib}/gconv/gconv-modules.cache r,
  /usr/lib/locale/locale-archive r,

  # --- Daemon entry points (one child per class) ---
  /usr/sbin/nginx cx -> nginx,
  /usr/sbin/sshd cx -> sshd,
  /usr/bin/dbus-daemon cx -> dbus-system,
  /usr/bin/pulseaudio cx -> pulseaudio,
  /lsiopy/bin/selkies cx -> selkies,
  /usr/bin/dbus-run-session cx -> desktop,
  /usr/bin/xdg-settings cx -> desktop,
  # svc-agent-desktop-api execs venv/bin/python (a symlink to the system
  # interpreter). The viewer's python is entered through change_profile.
  /usr/bin/python3.14 cx -> api,
  @{gs_tools}/chrome-idle cx -> chrome-control,
  # App sessions (svc-agent-desktop-apps, cont-finish, the host's pre-stop)
  # run desktop apps, so they share the desktop class.
  @{gs_tools}/app-session cx -> desktop,
  # cont-init seeds attach mode for both identities.
  /usr/local/bin/bladebro cx -> bladebro,
  # Podman's healthcheck (`sh -c "curl ... :3000/"`) and chrome-ensure here.
  /usr/bin/curl cx -> healthcheck,

  # --- Files ---
  / r,
  /etc/{passwd,group,shadow,gshadow,nsswitch.conf,localtime,login.defs,os-release,ld.so.cache} r,
  /usr/share/zoneinfo/** r,
  # init-adduser: usermod/groupmod rewrite the account databases.
  /etc/{passwd,group,shadow,gshadow}{,+,-} rw,
  /etc/{passwd,group,shadow,gshadow}.lock rwk,
  /etc/.pwd.lock rwk,
  /etc/default/useradd r,
  /etc/s6-overlay/s6-rc.d/init-adduser/branding r,
  /build_version r,
  /dev/null rw,
  /dev/urandom r,
  /dev/tty rw,
  /proc/ r,
  /proc/[0-9]*/{cmdline,stat,status,comm,cwd} r,
  /proc/[0-9]*/fd/ r,
  /proc/1/environ r,
  /proc/sys/kernel/{cap_last_cap,ngroups_max} r,
  /sys/fs/cgroup/ r,
  /sys/fs/cgroup/** r,

  # s6 runtime state, container environment (written by init scripts).
  /run/ r,
  /run/s6/ rw,
  /run/s6/** rwk,
  /run/service/ rw,
  /run/service/** rwkl,
  /run/s6-rc rw,
  /run/s6-rc:s6-rc-init:*/ rw,
  /run/s6-rc:s6-rc-init:*/** rwkl,
  /run/s6-linux-init-container-results/ rw,
  /run/s6-linux-init-container-results/** rw,
  /run/sshd/ rw,
  /run/dbus/ rw,
  /run/dbus/pid w,

  # lsiown inspects the roots (maxdepth 0); the webtop init scripts copy
  # defaults and patch configuration.
  /app/ rw,
  /defaults/ rw,
  /defaults/** r,
  /defaults/{pid,native} w,
  /defaults/startwm_wayland.sh rw,
  /defaults/sed* rw,
  /de-pid w,
  /etc/nginx/sites-available/ r,
  /etc/nginx/sites-available/default rw,
  /etc/nginx/sites-available/sed* rw,
  /usr/share/selkies/ rw,
  /usr/share/selkies/** rwl,
  /proot-apps/ r,
  /proot-apps/* r,
  # init-selkies-config re-asserts sudo's setuid bit and NOPASSWD in sudoers.
  /etc/sudoers rw,
  /etc/sed* rw,
  /usr/bin/sudo.ws w,
  /usr/bin/xdg-open w,
  /dev/input/ rw,
  /dev/dri/ r,
  /dev/dri/* r,
  /dev/shm/audio.lock rw,
  /tmp/ r,
  /tmp/selkies* rw,
  # Our cont-init: persistent directories, the sshd host key, Camoufox cleanup.
  /config/ rw,
  @{gs_data}/ rw,
  @{gs_data}/{chrome,logs,bladebro,ssh,runs}/ rw,
  @{gs_data}/chrome/{agent,personal}/ rw,
  @{gs_data}/bladebro/{agent,personal}/ rw,
  @{gs_data}/ssh/** rw,
  @{gs_data}/runs/{paused,state}/ rw,
  @{gs_data}/profiles/ rw,
  @{gs_data}/profiles/** rw,
  /config/.cache/ r,
  /config/.cache/camoufox/ rw,
  /config/.cache/camoufox/** rw,
  /config/.ssh/ rw,
  /config/.config/ rw,
  /config/.config/labwc/ rw,
  /config/.config/labwc/{autostart,menu.xml,menu.xml.bak,rc.xml} rw,
  /config/.config/pulse/cookie r,
  /config/.XDG/ rw,
  /config/.XDG/** rw,
  /config/.local/ rw,
  /config/.local/** rw,
  /config/.bashrc rw,
  /config/Desktop/ rw,
  /config/ssl/ rw,
  /config/ssl/cert.{pem,key} rw,
  # pactl (svc-selkies sink setup) speaks to PulseAudio's socket.
  /defaults/native rw,
  # chrome-ensure (from the viewer) and chrome-stop-all.
  @{gs_svcdirs}/svc-agent-desktop-chrome-{agent,personal}/ r,
  /tmp/ghostship-chrome-ensure-{agent,personal}.lock rwk,

  # Podman's healthcheck runs `sh -c "/usr/bin/curl -fsS http://127.0.0.1:3000/"`;
  # chrome-ensure started from the viewer probes DevTools the same way.
  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/curl rm,
    @{gs_ld} mr,
    @{gs_libs_curl} mr,
    /etc/{ld.so.cache,nsswitch.conf,passwd,group,hosts,host.conf,gai.conf,resolv.conf,gnutls/config,ssl/openssl.cnf} r,
    /usr/lib/locale/locale-archive r,
    / r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
  }

  # nginx: the Selkies web client and reverse proxy (3000/3001) to Selkies
  # (8082), Pelorus (5100) and the viewer (7090). Master as root, workers as
  # www-data. It serves only the Selkies web root.
  profile nginx flags=(complain,attach_disconnected,mediate_deleted) {
    capability setuid,
    capability setgid,
    capability chown,
    capability kill,
    # The self-signed key is owned by abc (0600).
    capability dac_override,

    network inet stream,
    network inet6 stream,
    network unix stream,

    /usr/sbin/nginx mr,
    @{gs_ld} mr,
    @{gs_lib}/{libc.so.6,libcrypt.so.1.1.0,libcrypto.so.3,libpcre2-8.so.0.14.0,libssl.so.3,libz.so.1.3.1,libzstd.so.1.5.7} mr,
    /usr/lib/nginx/modules/ngx_http_fancyindex_module.so mr,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,resolv.conf} r,
    /usr/share/zoneinfo/** r,
    /etc/ssl/openssl.cnf r,
    /etc/nginx/ r,
    /etc/nginx/** r,
    /config/ssl/cert.{pem,key} r,
    /usr/share/selkies/ r,
    /usr/share/selkies/** r,
    /usr/share/nginx/** r,
    /var/log/nginx/ r,
    /var/log/nginx/*.log w,
    /var/lib/nginx/ rw,
    /var/lib/nginx/** rw,
    /run/nginx.pid rw,
    /dev/null rw,
    /dev/zero rw,
    /dev/urandom r,
    /proc/sys/kernel/random/boot_id r,
    /sys/devices/system/cpu/online r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//nginx,
  }

  # sshd on 2222: key-only logins for abc (the t3code agents' automation key
  # and operator keys). The listener, per-connection sshd-session and the
  # privilege-separated sshd-auth share this domain; the login shell, commands
  # and sftp-server enter agent-shell. Host key and authorized_keys are read
  # here; nothing else under /config is.
  profile sshd flags=(complain,attach_disconnected,mediate_deleted) {
    capability setuid,
    capability setgid,
    capability sys_chroot,
    capability chown,
    capability fowner,
    capability kill,
    # The persistent host key is owned by abc (0600) but read as root.
    capability dac_override,

    network inet stream,
    network unix stream,
    network unix dgram,

    /usr/sbin/sshd mr,
    /usr/lib/openssh/{sshd-session,sshd-auth} rix,
    @{gs_ld} mr,
    @{gs_lib}/{libaudit.so.1.0.0,libc.so.6,libcap-ng.so.0.0.0,libcom_err.so.2.1,libcrypt.so.1.1.0,libcrypto.so.3,libgssapi_krb5.so.2.2,libk5crypto.so.3.1,libkeyutils.so.1.10,libkrb5.so.3.3,libkrb5support.so.0.1,libpam.so.0.85.1,libpcre2-8.so.0.14.0,libresolv.so.2,libselinux.so.1,libwrap.so.0.7.6,libz.so.1.3.1,libzstd.so.1.5.7} mr,

    # The session's shell and subsystem are agent commands.
    /usr/bin/bash px -> ghostship-agent-desktop//agent-shell,
    /usr/bin/dash px -> ghostship-agent-desktop//agent-shell,
    /usr/lib/openssh/sftp-server px -> ghostship-agent-desktop//agent-shell,

    /etc/ssh/ghostship-sshd_config r,
    /etc/ssh/moduli r,
    /etc/{passwd,group,shadow,nsswitch.conf,localtime,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,shells,motd,nologin,hosts.allow,hosts.deny,environment,default/locale} r,
    /etc/ssl/openssl.cnf r,
    /usr/share/zoneinfo/** r,
    /run/motd.dynamic r,
    /run/nologin r,
    /run/sshd/ r,
    /run/sshd-agent-desktop.pid rw,
    /run/utmp rwk,
    /var/log/{wtmp,btmp,lastlog} rwk,
    /var/lib/wtmpdb/ r,
    /var/lib/wtmpdb/** rwk,
    @{gs_data}/ssh/ r,
    @{gs_data}/ssh/host/ r,
    @{gs_data}/ssh/host/ssh_host_ed25519_key{,.pub} r,
    @{gs_data}/ssh/authorized_keys{,.local} r,
    /config/ r,
    /config/.ssh/ r,
    /config/.ssh/{environment,rc} r,
    /config/.hushlogin r,
    /dev/null rw,
    /dev/urandom r,
    /dev/ptmx rw,
    /dev/pts/ r,
    /dev/pts/[0-9]* rw,
    /dev/tty rw,
    /proc/[0-9]*/oom_score_adj rw,
    /proc/[0-9]*/fd/ r,
    /proc/sys/crypto/fips_enabled r,
    /proc/sys/kernel/ngroups_max r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//sshd,
    signal (send) peer=ghostship-agent-desktop//agent-shell,
    signal (receive) peer=ghostship-agent-desktop//agent-shell,
  }

  # Agent SSH sessions (the t3code agents' shells, one-shot commands and sftp).
  # Tradeoff: an agent shell is inherently broad. Agents install software,
  # launch GUI applications on the desktop (ghostship-desktop-exec), run the
  # Playwright venv and the tools under /opt/ghostship-agent-desktop, and call
  # the Bladebro and Chrome helpers, so it may run any system executable. It is
  # scoped to the home's working areas, the session environment, the desktop
  # sockets and the tools dir. It gets no access to either identity's Chrome
  # profile, Bladebro state or run registry (those go through the bladebro and
  # chrome-control children), the sshd host key and authorized_keys, /config/.ssh,
  # the nginx key, or the s6 container environment (which holds the API token).
  # Executables under /config, /tmp or /dev/shm are not allowed.
  profile agent-shell flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    network unix dgram,
    network unix seqpacket,

    /usr/bin/* mrix,
    /usr/sbin/* mrix,
    /usr/libexec/** mrix,
    /usr/lib/openssh/sftp-server mrix,
    /usr/lib/git-core/* mrix,
    /usr/local/bin/* mrix,
    @{gs_tools}/{desktop-exec,write-session-env} rix,
    @{gs_tools}/venv/bin/* mrix,
    /lsiopy/bin/* mrix,
    # Helpers with their own domains.
    @{gs_tools}/{bladebro-cli-agent,bladebro-cli-personal,bladebro-mcp-agent,bladebro-mcp-personal,bladebro-env} px -> ghostship-agent-desktop//bladebro,
    /usr/local/bin/bladebro px -> ghostship-agent-desktop//bladebro,
    @{gs_tools}/{chrome-ensure,chrome-close,chrome-lease-reaper} px -> ghostship-agent-desktop//chrome-control,
    @{gs_tools}/{ghostship-chrome-instance,run-chrome} px -> ghostship-agent-desktop//chrome-instance-launcher,
    /opt/google/chrome/google-chrome px -> ghostship-agent-desktop//chrome-other,
    /usr/bin/sudo.ws px -> ghostship-agent-desktop//sudo,
    @{gs_tools}/app-session px -> ghostship-agent-desktop//desktop,
    # Agents reach a window's browser controls with `stage-control call`.
    @{gs_tools}/stage-control px -> ghostship-agent-desktop//stage-control,

    # System files (read and map only).
    / r,
    /etc/ r,
    /etc/** r,
    /usr/ r,
    /usr/** mr,
    /opt/ r,
    @{gs_tools}/ r,
    @{gs_tools}/** r,
    /lsiopy/ r,
    /lsiopy/** mr,
    /var/lib/dpkg/** r,
    /var/cache/fontconfig/** r,
    /dev/null rw,
    /dev/zero rw,
    /dev/full rw,
    /dev/{u,}random r,
    /dev/tty rw,
    /dev/ptmx rw,
    /dev/pts/[0-9]* rw,
    /dev/shm/ r,
    owner /dev/shm/** rwk,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,
    /proc/ r,
    /proc/[0-9]*/** r,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,version,mounts,filesystems,swaps,pressure/*} r,
    /proc/sys/** r,
    /sys/devices/** r,
    /sys/dev/char/** r,
    /sys/class/** r,
    /sys/bus/** r,
    /sys/fs/cgroup/** r,

    # Home: working areas only.
    /config/ r,
    /config/{.bashrc,.profile,.bash_logout,.sudo_as_admin_successful} r,
    /config/.bash_history rw,
    /config/{Desktop,Downloads}/ rw,
    /config/{Desktop,Downloads}/** rwkl,
    /config/.cache/ rw,
    /config/.cache/** rwkl,
    /config/.config/ r,
    /config/.config/** rwkl,
    /config/.local/ r,
    /config/.local/** rwkl,
    /config/Applications/ r,
    /config/Applications/** r,
    @{gs_data}/ r,
    @{gs_data}/session-env r,
    @{gs_data}/logs/ r,
    @{gs_data}/logs/** r,
    @{gs_data}/cdp-matrix/ rw,
    @{gs_data}/cdp-matrix/** rwk,
    # Desktop session sockets: the compositors (including the browser stages),
    # AT-SPI, the session bus, PulseAudio and Xwayland.
    @{gs_xdg}/ r,
    @{gs_xdg}/** rw,
    /defaults/native rw,
    /tmp/ r,
    owner /tmp/** rwkl,
    /tmp/.X11-unix/X0 rw,
    /tmp/dbus-* rw,
    /run/dbus/system_bus_socket rw,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//agent-shell,
    signal (receive) peer=ghostship-agent-desktop//sshd,
    signal (send) peer=ghostship-agent-desktop//{bladebro,chrome-control,chrome-instance-launcher,chrome-other,sudo},
    ptrace (read) peer=ghostship-agent-desktop//agent-shell,
  }

  # sudo for abc (the webtop grants NOPASSWD: ALL to the sudo group) and what
  # it runs: package installs by agents and a person's terminal. This is root
  # over the image filesystem; it may change system files and package
  # databases but not the Chrome profiles, Bladebro state, the run registry,
  # the sshd keys or the s6 container environment.
  profile sudo flags=(complain,attach_disconnected,mediate_deleted) {
    capability setuid,
    capability setgid,
    capability chown,
    capability dac_override,
    capability fowner,
    capability fsetid,
    capability kill,
    capability setfcap,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    network unix dgram,

    /usr/bin/sudo.ws mr,
    /usr/libexec/sudo/*.so* mr,
    /usr/bin/* mrix,
    /usr/sbin/* mrix,
    /usr/lib/apt/methods/* mrix,
    /usr/lib/apt/apt-helper mrix,
    /usr/libexec/** mrix,
    /var/lib/dpkg/info/* mrix,
    /usr/share/debconf/** mrix,
    /etc/** r,
    /usr/** mr,
    /var/lib/sudo/ rw,
    /var/lib/sudo/** rwk,
    /run/sudo/ rw,
    /run/sudo/** rwk,
    # Package management writes.
    /etc/ rw,
    /etc/** rwkl,
    /usr/ rw,
    /usr/** rwkl,
    /opt/ rw,
    /opt/google/ rw,
    /opt/google/** rwkl,
    /var/ r,
    /var/{lib,cache,log,tmp}/ rw,
    /var/{lib,cache,log,tmp}/** rwkl,
    /tmp/ rw,
    /tmp/** rwkl,
    /dev/null rw,
    /dev/{u,}random r,
    /dev/tty rw,
    /dev/pts/[0-9]* rw,
    /proc/ r,
    /proc/[0-9]*/** r,
    /proc/{meminfo,stat,cpuinfo,mounts,filesystems} r,
    /proc/sys/** r,
    /config/ r,
    /config/{Desktop,Downloads}/** rw,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{agent-shell,desktop},
    signal (send,receive) peer=ghostship-agent-desktop//sudo,
  }

  # Bladebro in real-browser attach mode: the CLI/MCP wrappers, bladebro-env,
  # the stdio gate and the bladebro binary. It drives Chrome over loopback
  # DevTools; it never launches a browser. Both identities' Bladebro state is
  # here (bladebro-env selects one by argument, which AppArmor cannot see).
  profile bladebro flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network unix stream,

    @{gs_tools}/{bladebro-cli-agent,bladebro-cli-personal,bladebro-mcp-agent,bladebro-mcp-personal,bladebro-env,bladebro-gate} r,
    /usr/bin/{dash,bash} mrix,
    @{gs_cu}/install mrix,
    /usr/local/bin/bladebro mrix,
    /usr/bin/python3.14 mrix,
    @{gs_tools}/chrome-ensure px -> ghostship-agent-desktop//chrome-control,
    @{gs_ld} mr,
    @{gs_libs_shell} mr,
    @{gs_libs_python} mr,
    @{gs_lib}/{libdl.so.2,libpthread.so.0} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,resolv.conf} r,
    /usr/share/zoneinfo/** r,
    /config/ r,
    @{gs_data}/ r,
    @{gs_data}/session-env r,
    @{gs_data}/bladebro/ rw,
    @{gs_data}/bladebro/** rwk,
    @{gs_data}/runs/ rw,
    @{gs_data}/runs/** rwk,
    @{gs_data}/chrome/{agent,personal}/DevToolsActivePort r,
    /tmp/ r,
    owner /tmp/** rwk,
    /dev/null rw,
    /dev/urandom r,
    /proc/[0-9]*/{stat,status,fd/} r,
    /proc/sys/kernel/random/boot_id r,
    /sys/devices/system/cpu/** r,
    /sys/fs/cgroup/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{agent-shell,desktop},
    signal (send,receive) peer=ghostship-agent-desktop//bladebro,
  }

  # Chrome lifecycle helpers: the chrome-idle service (lease reaper and idle
  # stop), chrome-ensure and chrome-close. They speak loopback DevTools and
  # start or stop the two Chrome services through s6's control FIFOs; they
  # never read browser profiles.
  profile chrome-control flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network unix stream,

    @{gs_tools}/{chrome-idle,chrome-ensure,chrome-lease-reaper,chrome-close} r,
    @{gs_tools}/tools/ r,
    @{gs_tools}/tools/cdp_ws.py r,
    @{gs_tools}/tools/__pycache__/** r,
    /usr/bin/bash mrix,
    /usr/bin/{curl,flock} mrix,
    @{gs_cu}/{date,id,seq,sleep,stat,touch} mrix,
    @{gs_s6}/s6-svc mrix,
    /command/s6-setuidgid r,
    @{gs_s6}/s6-setuidgid mrix,
    /usr/bin/python3.14 mrix,
    @{gs_ld} mr,
    @{gs_libs_shell} mr,
    @{gs_libs_curl} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,gnutls/config,ssl/openssl.cnf} r,
    /usr/share/zoneinfo/** r,
    /tmp/ r,
    /tmp/ghostship-chrome-ensure-{agent,personal}.lock rwk,
    /run/service/ r,
    @{gs_svcdirs}/svc-agent-desktop-chrome-{agent,personal}/ r,
    @{gs_svcdirs}/svc-agent-desktop-chrome-{agent,personal}/supervise/ r,
    @{gs_svcdirs}/svc-agent-desktop-chrome-{agent,personal}/supervise/{control,status,lock} rw,
    / r,
    /dev/null rw,
    /dev/urandom r,
    /proc/[0-9]*/{stat,status} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{agent-shell,bladebro,desktop},
    signal (send,receive) peer=ghostship-agent-desktop//chrome-control,
  }

  # One identity's Chrome launcher: the s6 run script (with-contenv, which
  # reads the container environment), s6-setuidgid and run-chrome. It starts
  # the browser stage, its virtual input and Chrome, and stops them in order.
  profile chrome-agent-launcher flags=(complain,attach_disconnected,mediate_deleted) {
    capability setuid,
    capability setgid,

    network inet stream,
    network inet6 stream,
    network unix stream,

    @{gs_svcdirs}/svc-agent-desktop-chrome-agent/run r,
    /usr/bin/with-contenv r,
    /usr/bin/{bash,dash,pwdx,pgrep,gnurm,setsid} mrix,
    @{gs_cu}/{cat,mkdir,seq,sleep} mrix,
    @{gs_s6o}/command/with-contenv rix,
    /package/admin/execline-2.9.7.0/command/execline mrix,
    @{gs_s6}/{s6-envdir,s6-setuidgid,s6-envuidgid,s6-applyuidgid} mrix,
    @{gs_tools}/run-chrome rix,
    @{gs_tools}/chrome-close rix,
    @{gs_tools}/tools/ r,
    @{gs_tools}/tools/cdp_ws.py r,
    @{gs_tools}/tools/__pycache__/** r,
    /usr/bin/python3.14 mrix,
    /usr/bin/sway px -> ghostship-agent-desktop//sway,
    @{gs_tools}/stage-control px -> ghostship-agent-desktop//stage-control,
    /opt/google/chrome/google-chrome px -> ghostship-agent-desktop//chrome-agent,
    @{gs_ld} mr,
    @{gs_libs_shell} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,resolv.conf} r,
    /usr/share/zoneinfo/** r,
    /run/s6/container_environment/ r,
    /run/s6/container_environment/* r,
    @{gs_data}/session-env r,
    @{gs_data}/chrome/agent/ rw,
    @{gs_data}/chrome/agent/{SingletonLock,SingletonCookie,SingletonSocket} w,
    "@{gs_data}/chrome/agent/Default/{Sessions/Session_*,Sessions/Tabs_*,Current Session,Last Session,Current Tabs,Last Tabs}" w,
    @{gs_xdg}/ r,
    @{gs_xdg}/ghostship-stage-agent rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/ r,
    /proc/[0-9]*/{cmdline,stat,status,cwd} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//chrome-agent-launcher,
    signal (send) peer=ghostship-agent-desktop//{chrome-agent,sway,stage-control},
    signal (receive) peer=ghostship-agent-desktop//{chrome-agent,sway,stage-control},
  }

  profile chrome-personal-launcher flags=(complain,attach_disconnected,mediate_deleted) {
    capability setuid,
    capability setgid,

    network inet stream,
    network inet6 stream,
    network unix stream,

    @{gs_svcdirs}/svc-agent-desktop-chrome-personal/run r,
    /usr/bin/with-contenv r,
    /usr/bin/{bash,dash,pwdx,pgrep,gnurm,setsid} mrix,
    @{gs_cu}/{cat,mkdir,seq,sleep} mrix,
    @{gs_s6o}/command/with-contenv rix,
    /package/admin/execline-2.9.7.0/command/execline mrix,
    @{gs_s6}/{s6-envdir,s6-setuidgid,s6-envuidgid,s6-applyuidgid} mrix,
    @{gs_tools}/run-chrome rix,
    @{gs_tools}/chrome-close rix,
    @{gs_tools}/tools/ r,
    @{gs_tools}/tools/cdp_ws.py r,
    @{gs_tools}/tools/__pycache__/** r,
    /usr/bin/python3.14 mrix,
    /usr/bin/sway px -> ghostship-agent-desktop//sway,
    @{gs_tools}/stage-control px -> ghostship-agent-desktop//stage-control,
    /opt/google/chrome/google-chrome px -> ghostship-agent-desktop//chrome-personal,
    @{gs_ld} mr,
    @{gs_libs_shell} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,resolv.conf} r,
    /usr/share/zoneinfo/** r,
    /run/s6/container_environment/ r,
    /run/s6/container_environment/* r,
    @{gs_data}/session-env r,
    @{gs_data}/chrome/personal/ rw,
    @{gs_data}/chrome/personal/{SingletonLock,SingletonCookie,SingletonSocket} w,
    "@{gs_data}/chrome/personal/Default/{Sessions/Session_*,Sessions/Tabs_*,Current Session,Last Session,Current Tabs,Last Tabs}" w,
    @{gs_xdg}/ r,
    @{gs_xdg}/ghostship-stage-personal rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/ r,
    /proc/[0-9]*/{cmdline,stat,status,cwd} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//chrome-personal-launcher,
    signal (send) peer=ghostship-agent-desktop//{chrome-personal,sway,stage-control},
    signal (receive) peer=ghostship-agent-desktop//{chrome-personal,sway,stage-control},
  }

  # Extra Chrome instances (ghostship-chrome-instance start|stop|list over SSH)
  # with the same run-chrome launcher, limited to profile names other than
  # agent and personal.
  profile chrome-instance-launcher flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network unix stream,

    @{gs_tools}/{ghostship-chrome-instance,run-chrome,chrome-close} rix,
    @{gs_tools}/tools/ r,
    @{gs_tools}/tools/cdp_ws.py r,
    @{gs_tools}/tools/__pycache__/** r,
    /usr/bin/{bash,dash,pgrep,gnurm,setsid,grep} mrix,
    @{gs_cu}/{basename,cat,cut,head,mkdir,nohup,seq,sleep} mrix,
    /usr/bin/python3.14 mrix,
    /usr/bin/sway px -> ghostship-agent-desktop//sway,
    @{gs_tools}/stage-control px -> ghostship-agent-desktop//stage-control,
    /opt/google/chrome/google-chrome px -> ghostship-agent-desktop//chrome-other,
    @{gs_ld} mr,
    @{gs_libs_shell} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,resolv.conf} r,
    /usr/share/zoneinfo/** r,
    @{gs_data}/session-env r,
    @{gs_data}/chrome/ r,
    @{gs_data}/chrome/@{gs_other}/ rw,
    @{gs_data}/chrome/@{gs_other}/{SingletonLock,SingletonCookie,SingletonSocket} w,
    "@{gs_data}/chrome/@{gs_other}/Default/{Sessions/Session_*,Sessions/Tabs_*,Current Session,Last Session,Current Tabs,Last Tabs}" w,
    @{gs_data}/logs/ rw,
    @{gs_data}/logs/*.log rw,
    @{gs_xdg}/ r,
    @{gs_xdg}/ghostship-stage-@{gs_other} rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/ r,
    /proc/[0-9]*/{cmdline,stat,status} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{agent-shell,desktop},
    signal (send,receive) peer=ghostship-agent-desktop//chrome-instance-launcher,
    signal (send) peer=ghostship-agent-desktop//{chrome-other,sway,stage-control},
    signal (receive) peer=ghostship-agent-desktop//{chrome-other,sway,stage-control},
  }

  # A browser stage: headless Sway (wlroots, GLES on the render node) with
  # swaybg, publishing its socket name through the config's `exec sh -c printf`.
  profile sway flags=(complain,attach_disconnected,mediate_deleted) {
    network unix stream,
    network netlink raw,

    /usr/bin/sway mr,
    # Keymap compilation (observed 2026-10-21: ~9k reads a minute).
    /usr/share/xkeyboard-config-2/ r,
    /usr/share/xkeyboard-config-2/** r,
    /usr/share/X11/xkb r,
    /usr/bin/swaybg mrix,
    /usr/bin/dash mrix,
    @{gs_cu}/printf mrix,
    @{gs_ld} mr,
    @{gs_libs_sway} mr,
    @{gs_lib}/gbm/dri_gbm.so mr,
    @{gs_lib}/gconv/gconv-modules.cache r,
    /usr/lib/locale/locale-archive r,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache} r,
    /etc/ghostship/browser-sway.conf r,
    /etc/fonts/** r,
    /etc/drirc r,
    /usr/share/{X11,fonts,fontconfig,icons,drirc.d,glvnd,vulkan,libdrm,libinput,libwacom,zoneinfo}/** r,
    /var/cache/fontconfig/** r,
    /config/.cache/fontconfig/** rwk,
    /config/.cache/mesa_shader_cache/ rw,
    /config/.cache/mesa_shader_cache/** rwk,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-[0-9]* rwk,
    @{gs_xdg}/ghostship-stage-* rw,
    /dev/null rw,
    /dev/urandom r,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,
    /dev/shm/ r,
    owner /dev/shm/wlroots-* rw,
    /proc/[0-9]*/{stat,status,cmdline,fd/} r,
    /sys/dev/char/ r,
    /sys/dev/char/** r,
    /sys/devices/platform/** r,
    /sys/devices/system/cpu/** r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{chrome-agent-launcher,chrome-personal-launcher,chrome-instance-launcher},
    signal (send,receive) peer=ghostship-agent-desktop//sway,
  }

  # stage-control: a stdlib Python client of a browser stage. It holds the
  # stage's virtual pointer and keyboard, gives each Chrome window an output
  # (sway IPC), captures windows (grim), sends browser-control input (wtype
  # for keys), reads Chrome window ids over loopback DevTools, and serves
  # runs/stage-<identity>.sock. Its `call` mode is how SSH agents reach it.
  profile stage-control flags=(complain,attach_disconnected,mediate_deleted) {
    network unix stream,
    network inet stream,
    network inet6 stream,

    @{gs_tools}/stage-control r,
    @{gs_tools}/lib/ r,
    @{gs_tools}/lib/*.py r,
    @{gs_tools}/lib/__pycache__/** rw,
    @{gs_tools}/tools/ r,
    @{gs_tools}/tools/cdp_ws.py r,
    @{gs_tools}/tools/__pycache__/** rw,
    /usr/bin/python3.14 mrix,
    @{gs_ld} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/python3/dist-packages/ r,
    /usr/lib/python3/dist-packages/PIL/ r,
    /usr/lib/python3/dist-packages/PIL/** mr,
    /usr/lib/python3/dist-packages/pillow*/** r,
    @{gs_lib}/lib{jpeg,png16,tiff,webp,webpdemux,webpmux,sharpyuv,lcms2,openjp2,freetype,imagequant,xcb,Xau,Xdmcp,lzma,zstd,jbig,deflate,LerC,brotlicommon,brotlidec,bz2,z,expat}.so* mr,
    /usr/bin/{grim,wtype} mrix,
    @{gs_lib}/lib{wayland-client,xkbcommon,png16,jpeg,pixman-1,ffi,m,c}.so* mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,
    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts} r,
    /usr/share/X11/xkb/** r,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-[0-9]* rw,
    @{gs_xdg}/ghostship-stage-*{,.sock} rw,
    @{gs_data}/runs/ rw,
    @{gs_data}/runs/stage-*.sock rw,
    @{gs_data}/runs/*.pause r,
    @{gs_data}/runs/{busy,paused}/ rw,
    @{gs_data}/runs/{busy,paused}/* rw,
    /dev/null rw,
    /dev/urandom r,
    /dev/shm/ r,
    owner /dev/shm/** rw,
    owner /tmp/* rw,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{chrome-agent-launcher,chrome-personal-launcher,chrome-instance-launcher},
  }

  # Google Chrome for the agent identity (browser, zygotes, renderers, GPU,
  # utility and crashpad processes). Sandbox: Chrome uses the unprivileged
  # user-namespace sandbox here (zygote in a new user and PID namespace with
  # CAP_SYS_ADMIN inside it; chrome-sandbox, the setuid fallback, never ran),
  # so it needs `userns`, sys_admin and sys_chroot in its own namespace, its
  # uid/gid maps, and ptrace between its own processes for crashpad.
  profile chrome-agent flags=(complain,attach_disconnected,mediate_deleted) {
    userns,
    capability sys_admin,
    capability sys_chroot,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink raw,
    network unix stream,
    network unix dgram,
    network unix seqpacket,

    /opt/google/chrome/google-chrome r,
    /usr/bin/bash mrix,
    @{gs_cu}/{cat,dirname,mkdir,readlink,touch} mrix,
    /opt/google/chrome/{chrome,chrome_crashpad_handler} mrix,
    /opt/google/chrome/ r,
    /opt/google/chrome/** mr,
    @{gs_ld} mr,
    @{gs_libs_chrome} mr,
    @{gs_lib}/{libGLESv2.so.2.1.0,libvulkan.so.1.4.341} mr,
    @{gs_lib}/{gbm,dri,gio/modules,gvfs,pulseaudio,qt6/plugins,gtk-3.0/modules,gdk-pixbuf-2.0}/** mr,
    @{gs_lib}/gconv/** r,
    /usr/lib/locale/locale-archive r,

    /etc/{passwd,group,nsswitch.conf,localtime,timezone,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,machine-id,mime.types,os-release,lsb-release,drirc,asound.conf} r,
    /etc/opt/chrome/ r,
    /etc/opt/chrome/** r,
    /etc/{fonts,xdg,gtk-3.0,pulse,ssl}/** r,
    /var/lib/dbus/machine-id r,
    /usr/share/{fonts,fontconfig,icons,mime,glib-2.0,zoneinfo,X11,drirc.d,glvnd,vulkan,libdrm,alsa,locale,themes,qt6,ca-certificates,applications,pixmaps,gtk-3.0,egl}/** r,
    /var/cache/fontconfig/** r,

    # This identity's profile and Bladebro downloads.
    @{gs_data}/chrome/agent/ rw,
    @{gs_data}/chrome/agent/** rwk,
    @{gs_data}/bladebro/agent/downloads/ rw,
    @{gs_data}/bladebro/agent/downloads/** rw,
    # State the stock wrapper and Chrome keep in the shared home.
    /config/ r,
    /config/Downloads/ rw,
    /config/Downloads/** rw,
    "/config/.config/google-chrome/Crash Reports/" rw,
    "/config/.config/google-chrome/Crash Reports/**" rwk,
    /config/.local/share/applications/ rw,
    /config/.local/share/applications/mimeapps.list rw,
    /config/.local/share/pki/ rw,
    /config/.local/share/pki/nssdb/ rw,
    /config/.local/share/pki/nssdb/** rwk,
    /config/.cache/fontconfig/ rw,
    /config/.cache/fontconfig/** rwk,
    /config/.cache/mesa_shader_cache/ rw,
    /config/.cache/mesa_shader_cache/** rwk,
    /config/.config/{dconf/user,gtk-3.0/**,lxqt/**,mimeapps.list,pulse/cookie} r,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-[0-9]* rw,
    @{gs_xdg}/dconf/user r,
    @{gs_xdg}/at-spi/bus_[0-9]* rw,
    /defaults/native rw,
    /tmp/ r,
    owner /tmp/.com.google.Chrome.* rw,
    owner /tmp/com.google.Chrome.*/ rw,
    owner /tmp/com.google.Chrome.*/** rw,
    owner /tmp/.org.chromium.Chromium.* rw,
    /tmp/dbus-* rw,
    /dev/shm/ r,
    owner /dev/shm/{.com.google.Chrome.*,.org.chromium.Chromium.*,pulse-shm-*} rw,
    /dev/null rw,
    /dev/{u,}random r,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,

    # Sandbox setup and process accounting.
    /proc/ r,
    /proc/[0-9]*/{uid_map,gid_map,setgroups,oom_score_adj,oom_adj} rw,
    /proc/[0-9]*/{stat,statm,status,cmdline,comm,maps,smaps,smaps_rollup,mountinfo,mounts,limits,io,environ,auxv,cgroup,sched} r,
    /proc/[0-9]*/{fd,fdinfo,task,ns}/ r,
    /proc/[0-9]*/ns/* r,
    /proc/[0-9]*/task/[0-9]*/{stat,status,comm} rw,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,version,filesystems,vmstat,pressure/*} r,
    /proc/sys/kernel/{yama/ptrace_scope,pid_max,osrelease,threads-max,shmmax,random/boot_id} r,
    /proc/sys/fs/inotify/max_user_watches r,
    /proc/sys/net/core/somaxconn r,
    /proc/sys/vm/overcommit_memory r,
    /sys/devices/system/cpu/** r,
    /sys/devices/system/node/** r,
    /sys/devices/virtual/tty/tty0/active r,
    /sys/devices/platform/** r,
    /sys/dev/char/ r,
    /sys/dev/char/** r,
    /sys/bus/pci/devices/ r,
    /sys/fs/cgroup/** r,
    /sys/kernel/mm/transparent_hugepage/** r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//chrome-agent-launcher,
    signal (send,receive) peer=ghostship-agent-desktop//chrome-agent,
    ptrace (trace,read,tracedby,readby) peer=ghostship-agent-desktop//chrome-agent,
  }

  profile chrome-personal flags=(complain,attach_disconnected,mediate_deleted) {
    userns,
    capability sys_admin,
    capability sys_chroot,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink raw,
    network unix stream,
    network unix dgram,
    network unix seqpacket,

    /opt/google/chrome/google-chrome r,
    /usr/bin/bash mrix,
    @{gs_cu}/{cat,dirname,mkdir,readlink,touch} mrix,
    /opt/google/chrome/{chrome,chrome_crashpad_handler} mrix,
    /opt/google/chrome/ r,
    /opt/google/chrome/** mr,
    @{gs_ld} mr,
    @{gs_libs_chrome} mr,
    @{gs_lib}/{libGLESv2.so.2.1.0,libvulkan.so.1.4.341} mr,
    @{gs_lib}/{gbm,dri,gio/modules,gvfs,pulseaudio,qt6/plugins,gtk-3.0/modules,gdk-pixbuf-2.0}/** mr,
    @{gs_lib}/gconv/** r,
    /usr/lib/locale/locale-archive r,

    /etc/{passwd,group,nsswitch.conf,localtime,timezone,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,machine-id,mime.types,os-release,lsb-release,drirc,asound.conf} r,
    /etc/opt/chrome/ r,
    /etc/opt/chrome/** r,
    /etc/{fonts,xdg,gtk-3.0,pulse,ssl}/** r,
    /var/lib/dbus/machine-id r,
    /usr/share/{fonts,fontconfig,icons,mime,glib-2.0,zoneinfo,X11,drirc.d,glvnd,vulkan,libdrm,alsa,locale,themes,qt6,ca-certificates,applications,pixmaps,gtk-3.0,egl}/** r,
    /var/cache/fontconfig/** r,

    @{gs_data}/chrome/personal/ rw,
    @{gs_data}/chrome/personal/** rwk,
    @{gs_data}/bladebro/personal/downloads/ rw,
    @{gs_data}/bladebro/personal/downloads/** rw,
    /config/ r,
    /config/Downloads/ rw,
    /config/Downloads/** rw,
    "/config/.config/google-chrome/Crash Reports/" rw,
    "/config/.config/google-chrome/Crash Reports/**" rwk,
    /config/.local/share/applications/ rw,
    /config/.local/share/applications/mimeapps.list rw,
    /config/.local/share/pki/ rw,
    /config/.local/share/pki/nssdb/ rw,
    /config/.local/share/pki/nssdb/** rwk,
    /config/.cache/fontconfig/ rw,
    /config/.cache/fontconfig/** rwk,
    /config/.cache/mesa_shader_cache/ rw,
    /config/.cache/mesa_shader_cache/** rwk,
    /config/.config/{dconf/user,gtk-3.0/**,lxqt/**,mimeapps.list,pulse/cookie} r,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-[0-9]* rw,
    @{gs_xdg}/dconf/user r,
    @{gs_xdg}/at-spi/bus_[0-9]* rw,
    /defaults/native rw,
    /tmp/ r,
    owner /tmp/.com.google.Chrome.* rw,
    owner /tmp/com.google.Chrome.*/ rw,
    owner /tmp/com.google.Chrome.*/** rw,
    owner /tmp/.org.chromium.Chromium.* rw,
    /tmp/dbus-* rw,
    /dev/shm/ r,
    owner /dev/shm/{.com.google.Chrome.*,.org.chromium.Chromium.*,pulse-shm-*} rw,
    /dev/null rw,
    /dev/{u,}random r,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,

    /proc/ r,
    /proc/[0-9]*/{uid_map,gid_map,setgroups,oom_score_adj,oom_adj} rw,
    /proc/[0-9]*/{stat,statm,status,cmdline,comm,maps,smaps,smaps_rollup,mountinfo,mounts,limits,io,environ,auxv,cgroup,sched} r,
    /proc/[0-9]*/{fd,fdinfo,task,ns}/ r,
    /proc/[0-9]*/ns/* r,
    /proc/[0-9]*/task/[0-9]*/{stat,status,comm} rw,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,version,filesystems,vmstat,pressure/*} r,
    /proc/sys/kernel/{yama/ptrace_scope,pid_max,osrelease,threads-max,shmmax,random/boot_id} r,
    /proc/sys/fs/inotify/max_user_watches r,
    /proc/sys/net/core/somaxconn r,
    /proc/sys/vm/overcommit_memory r,
    /sys/devices/system/cpu/** r,
    /sys/devices/system/node/** r,
    /sys/devices/virtual/tty/tty0/active r,
    /sys/devices/platform/** r,
    /sys/dev/char/ r,
    /sys/dev/char/** r,
    /sys/bus/pci/devices/ r,
    /sys/fs/cgroup/** r,
    /sys/kernel/mm/transparent_hugepage/** r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//chrome-personal-launcher,
    signal (send,receive) peer=ghostship-agent-desktop//chrome-personal,
    ptrace (trace,read,tracedby,readby) peer=ghostship-agent-desktop//chrome-personal,
  }

  # Chrome outside the two identities: extra instances and a person's Chrome
  # started from the desktop (default profile in /config/.config/google-chrome).
  profile chrome-other flags=(complain,attach_disconnected,mediate_deleted) {
    userns,
    capability sys_admin,
    capability sys_chroot,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink raw,
    network unix stream,
    network unix dgram,
    network unix seqpacket,

    /opt/google/chrome/google-chrome r,
    /usr/bin/bash mrix,
    @{gs_cu}/{cat,dirname,mkdir,readlink,touch} mrix,
    /opt/google/chrome/{chrome,chrome_crashpad_handler} mrix,
    /opt/google/chrome/ r,
    /opt/google/chrome/** mr,
    @{gs_ld} mr,
    @{gs_libs_chrome} mr,
    @{gs_lib}/{libGLESv2.so.2.1.0,libvulkan.so.1.4.341} mr,
    @{gs_lib}/{gbm,dri,gio/modules,gvfs,pulseaudio,qt6/plugins,gtk-3.0/modules,gdk-pixbuf-2.0}/** mr,
    @{gs_lib}/gconv/** r,
    /usr/lib/locale/locale-archive r,

    /etc/{passwd,group,nsswitch.conf,localtime,timezone,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,machine-id,mime.types,os-release,lsb-release,drirc,asound.conf} r,
    /etc/opt/chrome/ r,
    /etc/opt/chrome/** r,
    /etc/{fonts,xdg,gtk-3.0,pulse,ssl}/** r,
    /var/lib/dbus/machine-id r,
    /usr/share/{fonts,fontconfig,icons,mime,glib-2.0,zoneinfo,X11,drirc.d,glvnd,vulkan,libdrm,alsa,locale,themes,qt6,ca-certificates,applications,pixmaps,gtk-3.0,egl}/** r,
    /var/cache/fontconfig/** r,

    @{gs_data}/chrome/ r,
    @{gs_data}/chrome/@{gs_other}/ rw,
    @{gs_data}/chrome/@{gs_other}/** rwk,
    /config/ r,
    /config/Downloads/ rw,
    /config/Downloads/** rw,
    /config/.config/google-chrome/ rw,
    /config/.config/google-chrome/** rwk,
    /config/.cache/google-chrome/ rw,
    /config/.cache/google-chrome/** rwk,
    /config/.local/share/applications/ rw,
    /config/.local/share/applications/mimeapps.list rw,
    /config/.local/share/pki/ rw,
    /config/.local/share/pki/nssdb/ rw,
    /config/.local/share/pki/nssdb/** rwk,
    /config/.cache/fontconfig/ rw,
    /config/.cache/fontconfig/** rwk,
    /config/.cache/mesa_shader_cache/ rw,
    /config/.cache/mesa_shader_cache/** rwk,
    /config/.config/{dconf/user,gtk-3.0/**,lxqt/**,mimeapps.list,pulse/cookie} r,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-[0-9]* rw,
    @{gs_xdg}/dconf/user r,
    @{gs_xdg}/at-spi/bus_[0-9]* rw,
    /defaults/native rw,
    /tmp/ r,
    owner /tmp/.com.google.Chrome.* rw,
    owner /tmp/com.google.Chrome.*/ rw,
    owner /tmp/com.google.Chrome.*/** rw,
    owner /tmp/.org.chromium.Chromium.* rw,
    /tmp/dbus-* rw,
    /dev/shm/ r,
    owner /dev/shm/{.com.google.Chrome.*,.org.chromium.Chromium.*,pulse-shm-*} rw,
    /dev/null rw,
    /dev/{u,}random r,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,

    /proc/ r,
    /proc/[0-9]*/{uid_map,gid_map,setgroups,oom_score_adj,oom_adj} rw,
    /proc/[0-9]*/{stat,statm,status,cmdline,comm,maps,smaps,smaps_rollup,mountinfo,mounts,limits,io,environ,auxv,cgroup,sched} r,
    /proc/[0-9]*/{fd,fdinfo,task,ns}/ r,
    /proc/[0-9]*/ns/* r,
    /proc/[0-9]*/task/[0-9]*/{stat,status,comm} rw,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,version,filesystems,vmstat,pressure/*} r,
    /proc/sys/kernel/{yama/ptrace_scope,pid_max,osrelease,threads-max,shmmax,random/boot_id} r,
    /proc/sys/fs/inotify/max_user_watches r,
    /proc/sys/net/core/somaxconn r,
    /proc/sys/vm/overcommit_memory r,
    /sys/devices/system/cpu/** r,
    /sys/devices/system/node/** r,
    /sys/devices/virtual/tty/tty0/active r,
    /sys/devices/platform/** r,
    /sys/dev/char/ r,
    /sys/dev/char/** r,
    /sys/bus/pci/devices/ r,
    /sys/fs/cgroup/** r,
    /sys/kernel/mm/transparent_hugepage/** r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//{chrome-instance-launcher,agent-shell,desktop},
    signal (send,receive) peer=ghostship-agent-desktop//chrome-other,
    ptrace (trace,read,tracedby,readby) peer=ghostship-agent-desktop//chrome-other,
  }

  # The authenticated automation API (agent_desktop_api.py, stdlib only) on the
  # container network port 7080, proxying Pelorus on loopback 5100. It reads
  # its token from the environment.
  profile api flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,

    /usr/bin/python3.14 mr,
    @{gs_ld} mr,
    @{gs_libs_python} mr,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/locale/locale-archive r,
    @{gs_lib}/gconv/gconv-modules.cache r,
    @{gs_tools}/agent_desktop_api.py r,
    @{gs_tools}/venv/ r,
    @{gs_tools}/venv/pyvenv.cfg r,
    @{gs_tools}/venv/{bin,lib,lib/python3.14}/ r,
    @{gs_tools}/venv/lib/python3.14/site-packages/ r,
    @{gs_tools}/venv/lib/python3.14/site-packages/*.pth r,
    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,ssl/openssl.cnf} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/urandom r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
  }

  # The system D-Bus daemon (svc-dbus, as abc).
  profile dbus-system flags=(complain,attach_disconnected,mediate_deleted) {
    network unix stream,

    /usr/bin/dbus-daemon mr,
    @{gs_ld} mr,
    @{gs_lib}/{libapparmor.so.1.30.7,libaudit.so.1.0.0,libc.so.6,libcap-ng.so.0.0.0,libdbus-1.so.3.38.3,libexpat.so.1.11.2,libm.so.6,libpcre2-8.so.0.14.0,libselinux.so.1,libsystemd.so.0.42.0} mr,
    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,machine-id} r,
    /var/lib/dbus/machine-id r,
    /etc/dbus-1/ r,
    /etc/dbus-1/** r,
    /usr/share/dbus-1/ r,
    /usr/share/dbus-1/** r,
    /run/dbus/ rw,
    /run/dbus/system_bus_socket rw,
    /run/dbus/pid rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/[0-9]*/{cmdline,stat,status} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
  }

  # PulseAudio (svc-pulseaudio, as abc): null sinks so the browser keeps the
  # audio devices a real desktop has. Socket and pid under /defaults
  # (PULSE_RUNTIME_PATH).
  profile pulseaudio flags=(complain,attach_disconnected,mediate_deleted) {
    network unix stream,
    network unix dgram,
    network netlink raw,
    # PulseAudio re-executes itself at start (observed 2026-10-21).
    /usr/bin/pulseaudio rmix,

    @{gs_ld} mr,
    @{gs_lib}/{libFLAC.so.14.0.0,libX11-xcb.so.1.0.0,libX11.so.6.4.0,libXau.so.6.0.0,libXdmcp.so.6.0.0,libXext.so.6.4.0,libXtst.so.6.1.0,libapparmor.so.1.30.7,libasyncns.so.0.3.1,libatomic.so.1.2.0,libblkid.so.1.1.0,libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libc.so.6,libcap.so.2.75,libcom_err.so.2.1,libdbus-1.so.3.38.3,libffi.so.8.2.0,libgio-2.0.so.0.8800.0,libglib-2.0.so.0.8800.0,libgmodule-2.0.so.0.8800.0,libgobject-2.0.so.0.8800.0,libgomp.so.1.0.0,libgssapi_krb5.so.2.2,libidn2.so.0.4.0,libjson-glib-1.0.so.0.1000.8,libk5crypto.so.3.1,libkeyutils.so.1.10,libkrb5.so.3.3,libkrb5support.so.0.1,libltdl.so.7.3.3,libm.so.6,libmount.so.1.1.0,libmp3lame.so.0.0.0,libmpg123.so.0.49.4,libmvec.so.1,libnghttp2.so.14.29.2,libogg.so.0.8.6,libopus.so.0.11.1,liborc-0.4.so.0.42.0,libpcre2-8.so.0.14.0,libpsl.so.5.3.4,libpulse.so.0.24.3,libresolv.so.2,libselinux.so.1,libsnapd-glib-2.so.1.0.0,libsndfile.so.1.0.37,libsoup-3.0.so.0.7.4,libsoxr.so.0.1.2,libspeexdsp.so.1.5.2,libsqlite3.so.0.8.6,libsystemd.so.0.42.0,libtdb.so.1.4.14,libudev.so.1.7.12,libunistring.so.5.2.0,libvorbis.so.0.4.9,libvorbisenc.so.2.0.12,libwrap.so.0.7.6,libxcb.so.1.1.0,libz.so.1.3.1} mr,
    @{gs_lib}/pulseaudio/{libpulsecommon-17.0.so,libpulsecore-17.0.so} mr,
    /usr/lib/pulse-17.0+dfsg1/modules/*.so mr,
    @{gs_lib}/alsa-lib/** mr,
    @{gs_lib}/gconv/gconv-modules.cache r,
    /usr/lib/locale/locale-archive r,
    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,machine-id,asound.conf} r,
    /var/lib/dbus/machine-id r,
    /etc/pulse/ r,
    /etc/pulse/** r,
    /usr/share/{alsa,pulseaudio,zoneinfo}/** r,
    /defaults/ r,
    /defaults/{native,pid} rwk,
    /config/ r,
    /config/.config/ r,
    /config/.config/pulse/ rw,
    /config/.config/pulse/** rwk,
    /run/dbus/system_bus_socket rw,
    /tmp/.X11-unix/X0 rw,
    /dev/null rw,
    /dev/urandom r,
    /dev/shm/ r,
    owner /dev/shm/pulse-shm-* rw,
    /dev/snd/ r,
    /proc/[0-9]*/{cmdline,stat,status} r,
    /proc/sys/kernel/random/boot_id r,
    /sys/devices/** r,
    /sys/class/sound/ r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//pulseaudio,
  }

  # Selkies 2 (the /lsiopy venv): the Wayland compositor and stream for the
  # human desktop (wayland-1, loopback 8082 and 5000). Its web client can run
  # shell commands (SELKIES_COMMAND_ENABLED, the dashboard's app launcher);
  # those shells run in the desktop child. File transfers land in ~/Desktop.
  profile selkies flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network unix stream,
    network unix dgram,
    network unix seqpacket,
    network netlink raw,

    /lsiopy/bin/selkies r,
    /usr/bin/python3.14 mrix,
    /usr/bin/{pactl,pgrep,xrdb,xrandr,gsettings} mrix,
    /usr/bin/dash px -> ghostship-agent-desktop//desktop,
    /usr/bin/bash px -> ghostship-agent-desktop//desktop,
    @{gs_ld} mr,
    @{gs_lib}/{libEGL.so.1.1.0,libEGL_mesa.so.0.0.0,libFLAC.so.14.0.0,libGLdispatch.so.0.0.0,libICE.so.6.3.0,libLLVM.so.21.1,libSM.so.6.0.1,libX11-xcb.so.1.0.0,libX11.so.6.4.0,libXau.so.6.0.0,libXdmcp.so.6.0.0,libXext.so.6.4.0,libXfixes.so.3.1.0,libapparmor.so.1.30.7,libasyncns.so.0.3.1,libbsd.so.0.12.2,libbz2.so.1.0.4,libc.so.6,libcrypto.so.3,libdbus-1.so.3.38.3,libdl.so.2,libdrm.so.2.131.0,libdrm_amdgpu.so.1.131.0,libedit.so.2.0.76,libelf-0.194.so,libexpat.so.1.11.2,libffi.so.8.2.0,libgallium-26.0.8-1ubuntu0.3.so,libgbm.so.1.0.0,libgcc_s.so.1,liblzma.so.5.8.3,libm.so.6,libmd.so.0.1.0,libmp3lame.so.0.0.0,libmpg123.so.0.49.4,libmvec.so.1,libogg.so.0.8.6,libopus.so.0.11.1,libpixman-1.so.0.46.4,libpthread.so.0,libpulse.so.0.24.3,libresolv.so.2,librt.so.1,libsensors.so.5.0.0,libsndfile.so.1.0.37,libssl.so.3,libstdc++.so.6.0.35,libsystemd.so.0.42.0,libtinfo.so.6.6,libuuid.so.1.3.0,libva-drm.so.2.2300.0,libva-x11.so.2.2300.0,libva.so.2.2300.0,libvorbis.so.0.4.9,libvorbisenc.so.2.0.12,libwayland-client.so.0.24.0,libwayland-server.so.0.24.0,libxcb-dri3.so.0.1.0,libxcb-present.so.0.0.0,libxcb-randr.so.0.1.0,libxcb-shm.so.0.0.0,libxcb-sync.so.1.0.0,libxcb-xfixes.so.0.0.0,libxcb.so.1.1.0,libxkbcommon.so.0.13.1,libxml2.so.16.1.2,libxshmfence.so.1.0.0,libz.so.1.3.1,libzstd.so.1.5.7} mr,
    @{gs_libs_pactl} mr,
    @{gs_libs_shell} mr,
    @{gs_lib}/{libXmuu.so.1.0.0,libXrandr.so.2.2.0,libXrender.so.1.3.0,libgio-2.0.so.0.8800.0,libglib-2.0.so.0.8800.0,libgmodule-2.0.so.0.8800.0,libgobject-2.0.so.0.8800.0,libmount.so.1.1.0,libblkid.so.1.1.0,libatomic.so.1.2.0} mr,
    @{gs_lib}/{gbm,dri}/** mr,
    @{gs_lib}/gconv/gconv-modules.cache r,
    /usr/lib/locale/locale-archive r,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /lsiopy/ r,
    /lsiopy/pyvenv.cfg r,
    /lsiopy/lib/python3.14/site-packages/ r,
    /lsiopy/lib/python3.14/site-packages/** r,
    /lsiopy/lib/python3.14/site-packages/**.so* mr,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,machine-id,mime.types,drirc,ssl/openssl.cnf} r,
    /etc/fonts/** r,
    /usr/share/{selkies,X11,icons,fonts,fontconfig,drirc.d,glvnd,vulkan,libdrm,zoneinfo,glib-2.0}/** r,
    /var/cache/fontconfig/** r,
    /config/ r,
    /config/.cache/mesa_shader_cache/ rw,
    /config/.cache/mesa_shader_cache/** rwk,
    /config/.config/pulse/cookie r,
    /config/Desktop/ rw,
    /config/Desktop/** rw,
    @{gs_xdg}/ r,
    @{gs_xdg}/wayland-1{,.lock} rwk,
    /defaults/native rw,
    /tmp/ r,
    /tmp/selkies* rw,
    /tmp/selkies_web*/ rw,
    /tmp/selkies_web*/** rw,
    /tmp/.X11-unix/X0 rw,
    /dev/null rw,
    /dev/{u,}random r,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,
    /dev/shm/ r,
    owner /dev/shm/** rw,
    /proc/ r,
    /proc/[0-9]*/{stat,statm,status,cmdline,comm,io,fd/} r,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,net/dev} r,
    /proc/sys/kernel/random/boot_id r,
    /sys/devices/** r,
    /sys/dev/char/** r,
    /sys/class/drm/ r,
    /sys/class/drm/** r,
    /sys/fs/cgroup/** r,
    /run/udev/data/** r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (send,receive) peer=ghostship-agent-desktop//selkies,
  }

  # Pelorus (the /lsiopy venv): AT-SPI desktop control, labwc IPC and the
  # Pixelflux computer-use endpoint on loopback 5000; serves on 5100.
  profile pelorus flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,

    /lsiopy/bin/pelorus r,
    /usr/bin/python3.14 mrix,
    @{gs_ld} mr,
    @{gs_lib}/{libX11.so.6.4.0,libXRes.so.1.0.0,libXau.so.6.0.0,libXdmcp.so.6.0.0,libXext.so.6.4.0,libXi.so.6.1.0,libatomic.so.1.2.0,libatspi.so.0.0.1,libblkid.so.1.1.0,libbz2.so.1.0.4,libc.so.6,libcrypto.so.3,libdbus-1.so.3.38.3,libdl.so.2,libexpat.so.1.11.2,libffi.so.8.2.0,libgcc_s.so.1,libgio-2.0.so.0.8800.0,libgirepository-2.0.so.0.8800.0,libglib-2.0.so.0.8800.0,libgmodule-2.0.so.0.8800.0,libgobject-2.0.so.0.8800.0,liblzma.so.5.8.3,libm.so.6,libmount.so.1.1.0,libpcre2-8.so.0.14.0,libpthread.so.0,librt.so.1,libselinux.so.1,libssl.so.3,libsystemd.so.0.42.0,libuuid.so.1.3.0,libxcb.so.1.1.0,libz.so.1.3.1,libzstd.so.1.5.7} mr,
    @{gs_lib}/girepository-1.0/*.typelib r,
    @{gs_lib}/gconv/gconv-modules.cache r,
    /usr/lib/locale/locale-archive r,
    /usr/lib/python3.14/ r,
    /usr/lib/python3.14/** r,
    /usr/lib/python3.14/lib-dynload/*.so mr,
    /usr/lib/python3/dist-packages/ r,
    /usr/lib/python3/dist-packages/** r,
    /usr/lib/python3/dist-packages/**.so mr,
    /lsiopy/ r,
    /lsiopy/pyvenv.cfg r,
    /lsiopy/lib/python3.14/site-packages/ r,
    /lsiopy/lib/python3.14/site-packages/** r,
    /lsiopy/lib/python3.14/site-packages/**.so* mr,

    /etc/{passwd,group,nsswitch.conf,localtime,ld.so.cache,hosts,host.conf,gai.conf,resolv.conf,machine-id,mime.types,ssl/openssl.cnf} r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/** r,
    /usr/share/{ca-certificates,zoneinfo}/** r,
    /var/lib/dbus/machine-id r,
    /config/ r,
    @{gs_xdg}/ r,
    @{gs_xdg}/at-spi/bus_[0-9]* rw,
    @{gs_xdg}/labwc.sock rw,
    @{gs_xdg}/wayland-0 rw,
    /tmp/dbus-* rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/[0-9]*/{stat,status,cmdline,comm} r,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//desktop,
    signal (send,receive) peer=ghostship-agent-desktop//pelorus,
  }

  # The human desktop session (startwm's dbus-run-session onward): session and
  # accessibility buses, labwc, Xwayland, LXQt, portals, gvfs, and whatever a
  # person launches from the panel, runner, a terminal or the Selkies
  # launcher. Like agent-shell it is inherently broad: any system executable,
  # plus applications a person installed under ~/Applications (OrcaSlicer).
  # It gets the same home scope as agent-shell, writes the session
  # environment, and has no access to Chrome profiles, Bladebro state, the
  # run registry, sshd keys or the s6 container environment.
  profile desktop flags=(complain,attach_disconnected,mediate_deleted) {
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    network unix dgram,
    network unix seqpacket,
    network netlink raw,

    /usr/bin/* mrix,
    /usr/libexec/** mrix,
    @{gs_lib}/libexec/** mrix,
    /usr/games/* mrix,
    /usr/local/bin/* mrix,
    @{gs_tools}/{write-session-env,desktop-exec,app-session} rix,
    # App sessions: GTK's image loaders find this bwrap stand-in first (see the file).
    @{gs_tools}/nobwrap/bwrap rix,
    # The person-installed OrcaSlicer AppImage tree (writable path; review on change).
    /config/Applications/orcaslicer/** mrix,
    # OrcaSlicer's embedded WebKitGTK helpers, and `ldd`, which runs the loader
    # (observed 2026-10-21: ~74k audit records/min in null profiles, 185 lost).
    # This child already runs any /usr/bin program; the loader adds no reach.
    @{gs_lib}/webkit2gtk-4.1/WebKit{Network,Web}Process mrix,
    @{gs_ld} mrix,
    /lsiopy/bin/pelorus px -> ghostship-agent-desktop//pelorus,
    /opt/google/chrome/google-chrome px -> ghostship-agent-desktop//chrome-other,
    /usr/bin/sudo.ws px -> ghostship-agent-desktop//sudo,
    @{gs_tools}/{chrome-ensure,chrome-close,chrome-lease-reaper} px -> ghostship-agent-desktop//chrome-control,
    @{gs_tools}/{ghostship-chrome-instance,run-chrome} px -> ghostship-agent-desktop//chrome-instance-launcher,
    @{gs_tools}/{bladebro-cli-agent,bladebro-cli-personal,bladebro-mcp-agent,bladebro-mcp-personal,bladebro-env} px -> ghostship-agent-desktop//bladebro,
    /usr/local/bin/bladebro px -> ghostship-agent-desktop//bladebro,

    / r,
    /etc/ r,
    /etc/** r,
    /usr/ r,
    /usr/** mr,
    /opt/ r,
    @{gs_tools}/ r,
    @{gs_tools}/** r,
    /var/cache/fontconfig/** r,
    /var/lib/dbus/machine-id r,
    /defaults/ r,
    /defaults/startwm_wayland.sh r,
    /defaults/native rw,
    /run/dbus/system_bus_socket rw,
    /dev/null rw,
    /dev/zero rw,
    /dev/{u,}random r,
    /dev/tty rw,
    /dev/ptmx rw,
    /dev/pts/[0-9]* rw,
    /dev/dri/ r,
    /dev/dri/renderD[0-9]* rw,
    /dev/shm/ r,
    owner /dev/shm/** rwk,
    /proc/ r,
    /proc/[0-9]*/** r,
    /proc/[0-9]*/oom_score_adj rw,
    /proc/{meminfo,stat,cpuinfo,loadavg,uptime,version,mounts,filesystems,swaps,pressure/*} r,
    /proc/sys/** r,
    /sys/devices/** r,
    /sys/dev/char/** r,
    /sys/class/** r,
    /sys/bus/** r,
    /sys/fs/cgroup/** r,
    /run/udev/data/** r,

    /config/ r,
    /config/{.bashrc,.profile,.bash_logout} r,
    /config/.bash_history rw,
    /config/{Desktop,Downloads,Applications}/ rw,
    /config/{Desktop,Downloads,Applications}/** rwkl,
    /config/.cache/ rw,
    /config/.cache/** rwkl,
    /config/.config/ rw,
    /config/.config/** rwkl,
    /config/.local/ rw,
    /config/.local/** rwkl,
    @{gs_xdg}/ rw,
    @{gs_xdg}/** rwkl,
    @{gs_data}/ r,
    @{gs_data}/session-env{,.tmp} rw,
    # App sessions: run records, pause/busy markers and control sockets.
    @{gs_data}/runs/ rw,
    @{gs_data}/runs/** rwk,
    /config/.ssh/ r,
    /config/.ssh/environment rw,
    /tmp/ r,
    /tmp/** rwkl,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-agent-desktop,
    signal (receive) peer=ghostship-agent-desktop//selkies,
    signal (send,receive) peer=ghostship-agent-desktop//desktop,
    signal (send) peer=ghostship-agent-desktop//{pelorus,chrome-other,sudo,bladebro,chrome-control,chrome-instance-launcher},
    ptrace (read) peer=ghostship-agent-desktop//desktop,
  }
}

# The desktop viewer (/agents/ behind Cloudflare Access): a Python server that
# relays agent browser windows over loopback DevTools. It may read its own
# code and the run registry, write pause and activity markers there, and use
# the network (loopback DevTools; Cloudflare Access signing keys over HTTPS),
# and start an idle-stopped Chrome through chrome-ensure, which runs under the
# container profile with a scrubbed environment. Browser profiles, SSH keys,
# secrets and every other executable are denied.
profile ghostship-desktop-viewer flags=(attach_disconnected,mediate_deleted) {
  include <abstractions/base>

  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  network unix stream,

  /usr/bin/python3* mrix,
  /usr/lib/python3*/** mr,
  /usr/local/lib/python3*/** r,
  /usr/lib/@{multiarch}/** mr,
  /etc/localtime r,
  /usr/share/zoneinfo/** r,
  /etc/mime.types r,
  /etc/nsswitch.conf r,
  /etc/hosts r,
  /etc/resolv.conf r,
  /etc/host.conf r,
  /etc/gai.conf r,
  /etc/ssl/certs/ r,
  /etc/ssl/certs/** r,
  /usr/share/ca-certificates/** r,
  /usr/lib/ssl/** r,
  /etc/passwd r,
  /etc/group r,
  @{PROC}/@{pid}/fd/ r,
  @{PROC}/@{pid}/stat r,

  /opt/ghostship-agent-desktop/viewer/ r,
  /opt/ghostship-agent-desktop/viewer/** r,
  /opt/ghostship-agent-desktop/tools/ r,
  /opt/ghostship-agent-desktop/tools/cdp_ws.py r,
  /opt/ghostship-agent-desktop/tools/__pycache__/** r,

  /opt/ghostship-agent-desktop/chrome-ensure Px -> ghostship-agent-desktop,

  /config/agent-desktop/runs/ rw,
  /config/agent-desktop/runs/** rwk,

  deny /config/agent-desktop/chrome/** rwklx,
  deny /config/agent-desktop/ssh/** rwklx,
  deny /config/.ssh/** rwklx,
  deny /run/s6/container_environment/** rwklx,
  deny capability,
  deny mount,
  deny ptrace,

  signal (receive) peer=ghostship-agent-desktop,
  signal (send) peer=ghostship-agent-desktop,
  signal (receive) peer=unconfined,
}
