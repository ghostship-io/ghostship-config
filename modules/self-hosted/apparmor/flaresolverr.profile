# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# ghcr.io/flaresolverr/flaresolverr:latest (FlareSolverr 3.5.2, image
# sha256:c80ae007ce2c), Debian 12, CPython 3.11 under dumb-init, Debian
# Chromium with undetected_chromedriver, Xvfb; uid/gid 1000 (flaresolverr),
# no effective capabilities, no_new_privs off.
# Chromium is started by utils.get_webdriver with --no-sandbox,
# --disable-setuid-sandbox, --no-zygote and --disable-gpu-sandbox: it needs no
# user namespaces, setuid helper or capabilities. Do not add any.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.

@{fs_libdir} = /usr/lib/aarch64-linux-gnu
@{fs_py} = /usr/local/lib/python3.11

profile ghostship-flaresolverr flags=(complain,attach_disconnected,mediate_deleted) {
  # dumb-init (PID 1) only forwards signals and execs the Python server.
  /usr/bin/dumb-init rix,
  @{fs_libdir}/ld-linux-aarch64.so.1 mr,
  @{fs_libdir}/libc.so.6 mr,
  /etc/ld.so.cache r,
  /dev/null rw,

  /usr/local/bin/python3.11 cx -> python,
  # Podman's healthcheck runs `/bin/sh -c "curl ..."`.
  /usr/bin/dash cx -> healthcheck,
  # The AppArmor review's heartbeat `podman exec flaresolverr /bin/cat`.
  /usr/bin/cat cx -> tools,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-flaresolverr,
  signal (send) peer=ghostship-flaresolverr//{python,chromedriver,chromium,xvfb},

  # The Bottle/Waitress API, selenium and undetected_chromedriver.
  profile python flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/local/bin/python3.11 rix,
    /usr/local/lib/libpython3.11.so.1.0 mr,
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/lib{c.so.6,m.so.6,pthread.so.0,bz2.so.1.0.4,crypto.so.3,ssl.so.3,ffi.so.8.1.2,lzma.so.5.4.1,uuid.so.1.3.0,z.so.1.2.13} mr,
    @{fs_libdir}/gconv/gconv-modules.cache r,
    @{fs_py}/ r,
    @{fs_py}/** r,
    @{fs_py}/lib-dynload/*.cpython-311-aarch64-linux-gnu.so mr,
    @{fs_py}/site-packages/**.cpython-311-aarch64-linux-gnu.so mr,

    # Application code. /app/__pycache__ is written at runtime by this uid and
    # then imported: a writable code path, see the review notes.
    /app/ r,
    /app/*.py r,
    /app/undetected_chromedriver/{,*.py} r,
    /app/bottle_plugins/{,*.py} r,
    /app/__pycache__/ rw,
    /app/__pycache__/*.pyc rw,
    /app/undetected_chromedriver/__pycache__/{,*.pyc} rw,
    /app/bottle_plugins/__pycache__/{,*.pyc} rw,
    /package.json r,
    # undetected_chromedriver patches /app/chromedriver in place (r+b) on
    # each browser start, then executes it: an intentional writable-binary exec.
    /app/chromedriver rw,
    /app/chromedriver cx -> chromedriver,
    /app/.local/ rw,
    /app/.local/share/ rw,
    /app/.local/share/undetected_chromedriver/ rw,

    # Browser and display launches. /usr/bin/chromium is a dash script.
    /usr/bin/chromium cx -> chromium,
    /usr/bin/Xvfb cx -> xvfb,
    # shutil.which/os.access probes for Xvfb and the Chrome candidates.
    /usr/{local/,}{bin,sbin}/ r,

    # Temporary Chrome profiles, proxy extensions and the Xvfb display lock.
    owner /tmp/ r,
    owner /tmp/** rwk,
    /tmp/ r,
    # multiprocessing semaphores (dprocess.start_detached).
    owner /dev/shm/sem.* rwk,
    owner /dev/shm/ r,

    /etc/{passwd,group,nsswitch.conf,hosts,resolv.conf,host.conf,gai.conf,localtime,ld.so.cache,os-release} r,
    /usr/share/zoneinfo/** r,
    /usr/lib/locale/** r,
    /dev/null rw,
    /dev/urandom r,
    /proc/{self,thread-self}/{fd/,stat,status,cgroup,mountinfo} r,
    /proc/stat r,
    /proc/meminfo r,
    /sys/devices/system/cpu/{,online,possible} r,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,

    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-flaresolverr,
    signal (send, receive) peer=ghostship-flaresolverr//python,
    signal (send) peer=ghostship-flaresolverr//{chromedriver,chromium,xvfb},
  }

  # The patched chromedriver: WebDriver HTTP on localhost, DevTools to Chrome.
  profile chromedriver flags=(complain,attach_disconnected,mediate_deleted) {
    /app/chromedriver rm,
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/lib{c.so.6,m.so.6,gcc_s.so.1,stdc++.so.6.0.30,Xau.so.6.0.0,Xdmcp.so.6.0.0,bsd.so.0.11.7,double-conversion.so.3.1,glib-2.0.so.0.7400.6,md.so.0.0.5,minizip.so.1.0.0,nspr4.so,nss3.so,nssutil3.so,pcre2-8.so.0.11.2,plc4.so,plds4.so,xcb.so.1.1.0,z.so.1.2.13,zstd.so.1.5.4} mr,
    /etc/{ld.so.cache,passwd,group,nsswitch.conf,hosts,resolv.conf,localtime} r,
    /dev/null rw,
    /dev/urandom r,
    /proc/{self,thread-self}/{fd/,stat,status,maps} r,
    /proc/sys/kernel/random/boot_id r,
    owner /tmp/** rwk,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-flaresolverr{,//python},
    signal (send, receive) peer=ghostship-flaresolverr//chromedriver,
  }

  # Debian's /usr/bin/chromium dash wrapper, then the browser, its own
  # re-exec'd helper processes (--type=...) and the crashpad handler.
  profile chromium flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/chromium r,
    /usr/bin/dash rix,
    # Wrapper helpers: uname, the crash-report cleanup find (and its rm),
    # chromium.d's expr, findmnt (dev-shm), ls (extensions), grep, tr, cut.
    /usr/bin/{uname,find,rm,expr,findmnt,ls,grep,tr,cut} rix,
    /etc/chromium.d/ r,
    /etc/chromium.d/{README,apikeys,default-flags,dev-shm,extensions} r,
    /usr/share/chromium/extensions/ r,
    /usr/lib/chromium/chromium rix,
    /usr/lib/chromium/chrome_crashpad_handler rix,
    /usr/lib/chromium/ r,
    /usr/lib/chromium/** r,
    /usr/lib/chromium/lib{EGL.so,GLESv2.so,vk_swiftshader.so,vulkan.so.1} mr,
    /etc/chromium/{,master_preferences} r,

    # NEEDED closure of chromium/crashpad/wrapper tools plus the libraries
    # Chromium dlopens (GTK3, NSS softokn/freebl/ckbi/dbm, GLX, gio dconf).
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/lib{c.so.6,m.so.6,dl.so.2,pthread.so.0,resolv.so.2,gcc_s.so.1,stdc++.so.6.0.30} mr,
    @{fs_libdir}/lib{EGL.so.1,GL.so.1.7.0,GLX.so.0.0.0,GLX_mesa.so.0.0.0,GLdispatch.so.0.0.0,glapi.so.0.0.0,gbm.so.1.0.0,drm.so.2.4.0,epoxy.so.0.0.0,xshmfence.so.1.0.0} mr,
    @{fs_libdir}/lib{X11-xcb.so.1.0.0,X11.so.6.4.0,XNVCtrl.so.0.0.0,Xau.so.6.0.0,Xcomposite.so.1.0.0,Xcursor.so.1.0.2,Xdamage.so.1.1.0,Xdmcp.so.6.0.0,Xext.so.6.4.0,Xfixes.so.3.1.0,Xi.so.6.1.0,Xinerama.so.1.0.0,Xrandr.so.2.2.0,Xrender.so.1.3.0,Xxf86vm.so.1.0.0} mr,
    @{fs_libdir}/libxcb{,-dri2,-dri3,-glx,-present,-randr,-render,-shm,-sync,-xfixes}.so.* mr,
    @{fs_libdir}/lib{xkbcommon.so.0.0.0,wayland-client.so.0.21.0,wayland-cursor.so.0.21.0,wayland-egl.so.1.21.0,wayland-server.so.0.21.0} mr,
    @{fs_libdir}/lib{gtk-3.so.0.2406.32,gdk-3.so.0.2406.32,gdk_pixbuf-2.0.so.0.4200.10,cairo.so.2.11600.0,cairo-gobject.so.2.11600.0,pango-1.0.so.0.5000.12,pangocairo-1.0.so.0.5000.12,pangoft2-1.0.so.0.5000.12,harfbuzz.so.0.60000.0,harfbuzz-subset.so.0.60000.0,graphite2.so.3.2.1,fontconfig.so.1.12.0,freetype.so.6.18.3,fribidi.so.0.4.0,thai.so.0.3.1,datrie.so.1.4.0,pixman-1.so.0.42.2,png16.so.16.39.0,jpeg.so.62.3.0,openjp2.so.2.5.0,lcms2.so.2.0.14} mr,
    @{fs_libdir}/lib{atk-1.0.so.0.24609.1,atk-bridge-2.0.so.0.0.0,atspi.so.0.0.1,dbus-1.so.3.32.4,glib-2.0.so.0.7400.6,gio-2.0.so.0.7400.6,gobject-2.0.so.0.7400.6,gmodule-2.0.so.0.7400.6,ffi.so.8.1.2,expat.so.1.8.10,pcre2-8.so.0.11.2,selinux.so.1,mount.so.1.1.0,blkid.so.1.1.0,smartcols.so.1.1.0,udev.so.1.7.5,systemd.so.0.35.0,cap.so.2.66,bsd.so.0.11.7,md.so.0.0.5} mr,
    @{fs_libdir}/lib{nspr4.so,nss3.so,nssutil3.so,smime3.so,plc4.so,plds4.so,softokn3.so,freebl3.so,freeblpriv3.so,nssckbi.so,nssdbm3.so,sqlite3.so.0.8.6} mr,
    @{fs_libdir}/lib{softokn3,freebl3,freeblpriv3,nssdbm3}.chk r,
    @{fs_libdir}/lib{cups.so.2,avahi-client.so.3.2.9,avahi-common.so.3.5.4,gnutls.so.30.34.3,nettle.so.8.6,hogweed.so.6.6,gmp.so.10.4.1,tasn1.so.6.6.3,p11-kit.so.0.3.0,idn2.so.0.3.8,unistring.so.2.2.0,gssapi_krb5.so.2.2,krb5.so.3.3,k5crypto.so.3.1,krb5support.so.0.1,com_err.so.2.1,keyutils.so.1.10,gcrypt.so.20.4.1,gpg-error.so.0.33.1} mr,
    @{fs_libdir}/lib{asound.so.2.0.0,asyncns.so.0.3.1,pulse.so.0.24.2,sndfile.so.1.0.35,FLAC.so.12.0.0,ogg.so.0.8.5,opus.so.0.8.0,vorbis.so.0.4.9,vorbisenc.so.2.0.12,mp3lame.so.0.0.0,mpg123.so.0.47.0,dav1d.so.6.6.0,openh264.so.2.3.1,double-conversion.so.3.1,minizip.so.1.0.0,brotlicommon.so.1.0.9,brotlidec.so.1.0.9,lz4.so.1.9.4,lzma.so.5.4.1,z.so.1.2.13,zstd.so.1.5.4} mr,
    @{fs_libdir}/pulseaudio/libpulsecommon-16.1.so mr,
    @{fs_libdir}/gio/modules/{giomodule.cache,libdconfsettings.so} mr,
    @{fs_libdir}/gdk-pixbuf-2.0/2.10.0/{loaders.cache,loaders/libpixbufloader-*.so} mr,
    @{fs_libdir}/gconv/gconv-modules.cache r,

    /etc/{ld.so.cache,passwd,group,nsswitch.conf,hosts,resolv.conf,host.conf,gai.conf,localtime,machine-id,mtab} r,
    /var/lib/dbus/machine-id r,
    /etc/fonts/** r,
    /etc/gtk-3.0/** r,
    /usr/share/{fonts,fontconfig,X11,icons,themes,mime,glib-2.0,locale,zoneinfo}/** r,
    /usr/lib/locale/** r,
    /var/cache/fontconfig/** r,

    # HOME=/app: crash reports and the fontconfig cache only.
    /app/ r,
    owner /app/.config/ rw,
    owner /app/.config/chromium/ rw,
    owner /app/.config/chromium/** rwk,
    owner /app/.cache/ rw,
    owner /app/.cache/fontconfig/ rw,
    owner /app/.cache/fontconfig/** rwk,
    # Temporary user-data-dir and --disable-dev-shm-usage shared memory files.
    /tmp/ r,
    owner /tmp/** rwkm,
    owner /dev/shm/ r,
    owner /dev/shm/** rwk,

    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/tty rw,
    /proc/ r,
    /proc/{self,thread-self}/** r,
    owner /proc/[0-9]*/{oom_score_adj,setgroups,uid_map,gid_map} rw,
    owner /proc/[0-9]*/{stat,statm,status,cmdline,maps,smaps,smaps_rollup,mem,auxv,environ,task/,task/[0-9]*/{stat,status,comm},fd/,io,cgroup,mountinfo,ns/} r,
    /proc/{stat,meminfo,cpuinfo,loadavg,uptime,version,filesystems,mounts} r,
    /proc/pressure/{cpu,memory,io} r,
    /proc/sys/kernel/{yama/ptrace_scope,random/boot_id,random/uuid,osrelease,hostname,shmmax,pid_max} r,
    /proc/sys/fs/inotify/max_user_watches r,
    /proc/sys/net/core/somaxconn r,
    /sys/devices/system/cpu/** r,
    /sys/devices/system/node/** r,
    /sys/fs/cgroup/{,**} r,

    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    # NetworkChangeNotifier's rtnetlink socket.
    network netlink raw,
    # X11 on the private Xvfb display; Mojo IPC over unnamed socketpairs.
    unix (connect, send, receive) type=stream peer=(label=ghostship-flaresolverr//xvfb, addr="@/tmp/.X11-unix/X[0-9]*"),
    unix (send, receive) type=stream peer=(label=ghostship-flaresolverr//chromium),
    unix (send, receive) type=seqpacket peer=(label=ghostship-flaresolverr//chromium),
    unix (send, receive) type=dgram peer=(label=ghostship-flaresolverr//chromium),
    unix (create, getattr, getopt, setopt, shutdown) type=stream,
    unix (create, getattr, getopt, setopt, shutdown) type=seqpacket,
    unix (create, getattr, getopt, setopt, shutdown) type=dgram,

    # crashpad attaches to the browser processes it monitors.
    ptrace (read, readby, trace, tracedby) peer=ghostship-flaresolverr//chromium,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-flaresolverr{,//python},
    signal (send, receive) peer=ghostship-flaresolverr//chromium,
  }

  # Xvfb for head-full Chrome; its keymap compile runs `sh -c xkbcomp`.
  profile xvfb flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/Xvfb rm,
    /usr/bin/dash rix,
    /usr/bin/xkbcomp rix,
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/lib{c.so.6,m.so.6,GL.so.1.7.0,GLX.so.0.0.0,GLdispatch.so.0.0.0,X11.so.6.4.0,Xau.so.6.0.0,Xdmcp.so.6.0.0,Xfont2.so.2.0.0,audit.so.1.0.0,brotlicommon.so.1.0.9,brotlidec.so.1.0.9,bsd.so.0.11.7,bz2.so.1.0.4,cap-ng.so.0.0.0,cap.so.2.66,fontenc.so.1.0.0,freetype.so.6.18.3,gcrypt.so.20.4.1,gpg-error.so.0.33.1,lz4.so.1.9.4,lzma.so.5.4.1,md.so.0.0.5,pcre2-8.so.0.11.2,pixman-1.so.0.42.2,png16.so.16.39.0,selinux.so.1,systemd.so.0.35.0,unwind.so.8.0.1,xcb.so.1.1.0,xkbfile.so.1.0.2,z.so.1.2.13,zstd.so.1.5.4} mr,
    /etc/{ld.so.cache,passwd,group,nsswitch.conf,localtime} r,
    /etc/X11/** r,
    /usr/share/X11/** r,
    /usr/share/fonts/** r,
    /tmp/ r,
    /tmp/.X11-unix/ rw,
    owner /tmp/.X11-unix/X[0-9]* rw,
    owner /tmp/.{,t}X[0-9]*-lock rw,
    owner /tmp/server-*.xkm rw,
    /dev/null rw,
    /dev/urandom r,
    /proc/{self,thread-self}/{fd/,stat,status,cmdline} r,
    unix (create, bind, listen, accept, send, receive, getattr, getopt, setopt, shutdown) type=stream addr="@/tmp/.X11-unix/X[0-9]*",
    unix (send, receive) type=stream peer=(label=ghostship-flaresolverr//chromium),
    unix (create, getattr, getopt, setopt, shutdown) type=stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-flaresolverr{,//python},
    signal (send, receive) peer=ghostship-flaresolverr//xvfb,
  }

  # Podman healthcheck: `curl -f --connect-timeout 5 http://127.0.0.1:8191/`.
  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/dash rix,
    /usr/bin/curl rix,
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/lib{c.so.6,resolv.so.2,curl.so.4.8.0,brotlicommon.so.1.0.9,brotlidec.so.1.0.9,com_err.so.2.1,crypto.so.3,ssl.so.3,ffi.so.8.1.2,gmp.so.10.4.1,gnutls.so.30.34.3,gssapi_krb5.so.2.2,hogweed.so.6.6,idn2.so.0.3.8,k5crypto.so.3.1,keyutils.so.1.10,krb5.so.3.3,krb5support.so.0.1,lber-2.5.so.0.1.8,ldap-2.5.so.0.1.8,nettle.so.8.6,nghttp2.so.14.24.1,p11-kit.so.0.3.0,psl.so.5.3.4,rtmp.so.1,sasl2.so.2.0.25,ssh2.so.1.0.1,tasn1.so.6.6.3,unistring.so.2.2.0,z.so.1.2.13,zstd.so.1.5.4} mr,
    /etc/{ld.so.cache,nsswitch.conf,passwd,hosts,resolv.conf,host.conf,gai.conf,ssl/openssl.cnf,gnutls/config} r,
    /usr/lib/locale/** r,
    / r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (send, receive) peer=ghostship-flaresolverr//healthcheck,
  }

  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    # Audit heartbeat only: no app, browser or network access.
    /usr/bin/cat rix,
    @{fs_libdir}/ld-linux-aarch64.so.1 mr,
    @{fs_libdir}/libc.so.6 mr,
    /etc/ld.so.cache r,
    /dev/null rw,
    audit /proc/sys/kernel/random/boot_id r,
    signal (receive) peer=unconfined,
    signal (send, receive) peer=ghostship-flaresolverr//tools,
  }
}
