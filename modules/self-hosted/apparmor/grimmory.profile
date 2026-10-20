# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/grimmory/grimmory:latest (sha256:bf6fe21c6e24...), Alpine 3.24.2
# musl; Eclipse Temurin JDK 25.0.4+7 at /opt/java/openjdk; Spring Boot
# /app/app.jar. The entrypoint runs as root (no image User), creates the
# booklore user (USER_ID/GROUP_ID 3000), chowns the data dirs and su-execs to
# uid/gid 3000; the JVM has no effective capabilities.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Domains: top = /usr/local/bin/entrypoint.sh (BusyBox sh) with getent,
# addgroup/adduser, mkdir/chown and su-exec, and the podman healthcheck
# (`sh -c "wget ... /api/v1/healthcheck"`, BusyBox, run as root). BusyBox
# applets cannot be separated by argv, so the healthcheck shares this startup
# domain. server = the JVM. ffprobe/kepubify = helper executables the JVM
# spawns via ProcessBuilder (audiobook chapters, Kobo kepub conversion).

@{grim_jdk} = /opt/java/openjdk

profile ghostship-grimmory flags=(complain,attach_disconnected,mediate_deleted) {
  /usr/local/bin/entrypoint.sh rix,
  /bin/{busybox,coreutils} rix,
  /usr/bin/getent rix,
  /sbin/su-exec rix,
  @{grim_jdk}/bin/java cx -> server,
  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/{libacl.so.1.1.2302,libattr.so.1.1.2502,libcrypto.so.3,libskarnet.so.2.15.0.0,libutmps.so.0.1.3.3} mr,

  # addgroup/adduser -S (rewrites the account databases on each fresh
  # container), the booklore home, and `chown 3000:3000` of the data roots.
  capability chown,
  # su-exec 3000:3000.
  capability setuid,
  capability setgid,
  /etc/{passwd,group,shadow} rwk,
  /etc/{passwd,group,shadow}+ rw,
  /etc/{passwd,group,shadow}- rw,
  /home/ r,
  /home/booklore/ rw,
  /app/data/ rw,
  /bookdrop/ rw,
  /books/ rw,
  / r,
  /etc/{hosts,resolv.conf,nsswitch.conf,localtime,login.defs} r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,
  # Healthcheck wget to 127.0.0.1:6060.
  network inet stream,
  network inet6 stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-grimmory,
  signal (send) peer=ghostship-grimmory//server,

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # JVM: image runtime and jar read-only; app data, libraries and bookdrop
    # are managed by the app (imports, moves, metadata writes, covers).
    # The launcher re-executes java once (observed 2026-10-20: server//null-java).
    @{grim_jdk}/bin/java rmix,
    /lib/ld-musl-aarch64.so.1 mr,
    @{grim_jdk}/lib/server/libjvm.so mr,
    # Observed mappings plus the AWT font/imaging and FFM lookup libraries
    # used for cover rendering and pdfium4j's native access.
    @{grim_jdk}/lib/{libjli,libjava,libjimage,libzip,libnet,libnio,libextnet,libmanagement,libmanagement_ext,libawt,libawt_headless,libjavajpeg,liblcms,libfontmanager,libfreetype,libmlib_image,libsyslookup,libprefs,libsleef,libverify}.so mr,
    @{grim_jdk}/lib/server/classes_nocoops_coh.jsa mr,
    @{grim_jdk}/ r,
    @{grim_jdk}/** r,
    /app/ r,
    /app/app.jar r,

    /usr/local/bin/ffprobe px -> ghostship-grimmory//ffprobe,
    /usr/local/bin/kepubify px -> ghostship-grimmory//kepubify,

    /app/data/ rw,
    /app/data/** rwk,
    /books/ rw,
    /books/** rwk,
    /audiobooks/ rw,
    /audiobooks/** rwk,
    /bookdrop/ rw,
    /bookdrop/** rwk,
    # Tomcat work/docbase dirs, hsperfdata, upload staging, pdfium4j extract.
    /tmp/ r,
    /tmp/** rwk,
    # SECURITY: pdfium4j extracts libpdfium.so and its shim from the jar into
    # a writable /tmp directory and loads them. This executable mapping from
    # a writable path is verified required for PDF rendering.
    /tmp/pdfium4j-[0-9]*/{libpdfium.so,pdfium4j_shim.so} mr,

    / r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,localtime,hostname,os-release} r,
    /etc/fonts/ r,
    /etc/fonts/** r,
    /usr/share/fonts/ r,
    /usr/share/fonts/** r,
    /var/cache/fontconfig/ r,
    /var/cache/fontconfig/** r,
    /usr/share/zoneinfo/ r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/ r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    # JVM container support, CPU/memory discovery and thread naming.
    /proc/{self,thread-self}/{stat,status,statm,maps,smaps,cgroup,mountinfo,mounts,limits,cmdline,auxv,coredump_filter} r,
    /proc/{self,thread-self}/task/ r,
    /proc/{self,thread-self}/task/[0-9]*/{stat,comm} rw,
    /proc/{meminfo,cpuinfo,stat,loadavg,uptime} r,
    /proc/sys/kernel/{osrelease,pid_max,threads-max} r,
    /proc/sys/vm/{overcommit_memory,max_map_count} r,
    /proc/net/{if_inet6,ipv6_route} r,
    /sys/devices/system/cpu/ r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/** r,
    /sys/kernel/mm/transparent_hugepage/{enabled,hpage_pmd_size,shmem_enabled} r,
    /sys/fs/cgroup/ r,
    /sys/fs/cgroup/{cgroup.controllers,cpu.max,cpu.weight,cpuset.cpus.effective,cpuset.mems.effective,memory.max,memory.high,memory.low,memory.min,memory.swap.max,memory.swap.current,memory.current,memory.stat,pids.max,pids.current,cpu.stat,io.stat} r,
    # Listens on :6060 (dual-stack); grimmory-db and metadata sources over
    # TCP; DNS.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-grimmory,
    signal (send, receive) peer=ghostship-grimmory//server,
    signal (send) peer=ghostship-grimmory//{ffprobe,kepubify},
  }

  profile ffprobe flags=(complain,attach_disconnected,mediate_deleted) {
    # Static ffprobe: read one audiobook, print chapters. No network, no exec.
    /usr/local/bin/ffprobe mr,
    /audiobooks/ r,
    /audiobooks/** r,
    /books/ r,
    /books/** r,
    /bookdrop/ r,
    /bookdrop/** r,
    /tmp/ r,
    /tmp/** r,
    /dev/null rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{stat,status} r,
    /proc/{cpuinfo,meminfo} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/fs/cgroup/cpu.max r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-grimmory//server,
  }

  profile kepubify flags=(complain,attach_disconnected,mediate_deleted) {
    # Static Go kepubify: read an EPUB, write the kepub to the output dir.
    /usr/local/bin/kepubify mr,
    /books/ r,
    /books/** r,
    /bookdrop/ r,
    /bookdrop/** r,
    /tmp/ r,
    /tmp/** rw,
    /dev/null rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{cgroup,mountinfo,maps,stat,status} r,
    /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
    /sys/fs/cgroup/cpu.max r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-grimmory//server,
  }
}
