# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/robertlordhood/chaptarr:latest (not LinuxServer), Ubuntu 24.04.5
# (glibc); framework-dependent .NET 10.0.12 (/usr/share/dotnet) running
# /app/Chaptarr.dll; uid/gid 3000:3000. Entrypoint /entrypoint.sh takes its
# non-root branch (no useradd/chown/gosu). Every process has CapEff=0: no
# capability rules. Root folder (from the database): /books only.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

@{ghostship_chaptarr_rt} = /usr/share/dotnet
@{ghostship_chaptarr_fx} = /usr/share/dotnet/shared/{Microsoft.NETCore.App,Microsoft.AspNetCore.App}/10.0.12
@{ghostship_chaptarr_core} = /usr/share/dotnet/shared/Microsoft.NETCore.App/10.0.12
@{ghostship_chaptarr_lib} = /usr/lib/aarch64-linux-gnu

profile ghostship-chaptarr flags=(complain,attach_disconnected,mediate_deleted) {
  # Entrypoint (bash) and the podman healthcheck's `sh -c` (dash) start here via
  # crun/podman exec. The non-root branch runs id, touch and rm on a /config
  # write probe, then `exec dotnet /app/Chaptarr.dll -nobrowser -data=/config`.
  /entrypoint.sh rix,
  /usr/bin/{bash,dash} rix,
  /usr/bin/{id,touch,rm,mkdir} rix,
  # Collector heartbeat: `podman exec <c> /bin/cat`.
  /usr/bin/cat rix,
  # /usr/bin/dotnet resolves to the runtime host.
  @{ghostship_chaptarr_rt}/dotnet cx -> server,
  # Healthcheck: `wget -q -O - ... /ping | grep -q '"status": "OK"'`.
  /usr/bin/{wget,grep} cx -> healthcheck,

  @{ghostship_chaptarr_lib}/ld-linux-aarch64.so.1 mr,
  @{ghostship_chaptarr_lib}/lib{c.so.6,tinfo.so.6.4,selinux.so.1,pcre2-8.so.0.11.2} mr,
  /etc/ld.so.cache r,

  # DATA_DIR write probe only; the server domain owns /config contents.
  /config/ r,
  /config/.write_test rw,

  / r,
  /{etc,usr,dev,proc}/ r,
  /etc/{passwd,group,nsswitch.conf,localtime,timezone} r,
  /usr/share/zoneinfo/** r,
  # libselinux (linked by id) probes for selinuxfs.
  /proc/filesystems r,
  /dev/null rw,
  /dev/{stdin,stdout,stderr} rw,
  /dev/fd/[0-9]* rw,
  /proc/{self,thread-self}/fd/ r,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-chaptarr,
  signal (send, receive) peer=ghostship-chaptarr//server,
  signal (send, receive) peer=ghostship-chaptarr//healthcheck,

  profile server flags=(complain,attach_disconnected,mediate_deleted) {
    # dotnet host -> hostfxr -> hostpolicy -> CoreCLR. No shell or other exec.
    @{ghostship_chaptarr_rt}/dotnet rix,
    @{ghostship_chaptarr_rt}/ r,
    @{ghostship_chaptarr_rt}/host/fxr/ r,
    @{ghostship_chaptarr_rt}/host/fxr/10.0.12/libhostfxr.so mr,
    @{ghostship_chaptarr_rt}/shared/ r,
    @{ghostship_chaptarr_rt}/shared/{Microsoft.NETCore.App,Microsoft.AspNetCore.App}/ r,
    @{ghostship_chaptarr_fx}/ r,
    @{ghostship_chaptarr_fx}/** r,
    # 682 framework assemblies are mapped (ReadyToRun code is executable).
    @{ghostship_chaptarr_fx}/*.dll mr,
    @{ghostship_chaptarr_core}/lib{clrjit,coreclr,hostpolicy,System.IO.Compression.Native,System.Native,System.Security.Cryptography.Native.OpenSsl}.so mr,

    # Application tree (root-owned, 0755): assemblies, runtimeconfig/deps,
    # localization and UI. Only these two native libraries are mapped.
    /app/ r,
    /app/** r,
    /app/*.dll mr,
    /app/lib{e_sqlite3,MonoPosixHelper}.so mr,

    @{ghostship_chaptarr_lib}/ld-linux-aarch64.so.1 mr,
    @{ghostship_chaptarr_lib}/lib{c.so.6,dl.so.2,m.so.6,pthread.so.0,rt.so.1,gcc_s.so.1,stdc++.so.6.0.33,crypto.so.3,ssl.so.3} mr,
    @{ghostship_chaptarr_lib}/libicu{data,i18n,uc}.so.74.2 mr,
    /etc/ld.so.cache r,

    # W^X double mapping and the diagnostics IPC marker.
    "/memfd:doublemapper" rwm,
    "/memfd:doublemapper (deleted)" rwm,
    "/memfd:dotnet_ipc_created" rw,
    "/memfd:dotnet_ipc_created (deleted)" rw,
    # The runtime diagnostics/debugger IPC is enabled in this image (no
    # DOTNET_EnableDiagnostics=0): it creates these in /tmp.
    /tmp/ r,
    /tmp/clr-debug-pipe-[0-9]*-[0-9]*-{in,out} rw,
    /tmp/dotnet-diagnostic-[0-9]*-[0-9]*-socket rw,

    # State: SQLite (chaptarr/logs/cache/staging .db with -shm/-wal), logs,
    # MediaCover, Backups, asp keys, pid file.
    /config/ rw,
    /config/** rwk,
    # /books is the configured root folder: import, rename and delete.
    /books/ rw,
    /books/** rw,
    # /downloads: completed-download import moves/copies and removes sources.
    /downloads/ rw,
    /downloads/** rw,
    # /audiobooks is mounted but is not a root folder today; read-only until
    # complain records show the app managing it.
    /audiobooks/ r,
    /audiobooks/** r,

    / r,
    /{etc,usr,usr/lib,usr/share,dev,proc,sys,tmp}/ r,
    /etc/{passwd,group,hosts,resolv.conf,host.conf,gai.conf,nsswitch.conf,services,protocols,localtime,timezone,os-release,fstab,mime.types} r,
    /usr/lib/os-release r,
    # OpenSSL dir /usr/lib/ssl links into /etc/ssl; the bundle links into
    # /usr/share/ca-certificates.
    /usr/lib/ssl/ r,
    /etc/ssl/ r,
    /etc/ssl/** r,
    /usr/share/ca-certificates/** r,
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

    # Kestrel on [::]:8789 (dual-stack), outbound HTTP(S) to indexers, the
    # download client and metadata services; glibc DNS; NETLINK_ROUTE for
    # network-change notification; the diagnostics unix stream listener.
    # AppArmor cannot restrict destinations.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network netlink raw,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (send, receive) peer=ghostship-chaptarr,
    signal (send, receive) peer=ghostship-chaptarr//server,
  }

  # GNU wget to loopback /ping piped into grep. No /config, app or media access.
  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/{wget,grep} rm,
    @{ghostship_chaptarr_lib}/ld-linux-aarch64.so.1 mr,
    @{ghostship_chaptarr_lib}/lib{c.so.6,pcre2-8.so.0.11.2,crypto.so.3,ssl.so.3,idn2.so.0.4.0,psl.so.5.3.4,unistring.so.5.0.0,uuid.so.1.3.0,z.so.1.3} mr,
    /etc/{ld.so.cache,wgetrc,hosts,resolv.conf,nsswitch.conf,host.conf,gai.conf,passwd} r,
    /etc/ssl/openssl.cnf r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-chaptarr,
    signal (send, receive) peer=ghostship-chaptarr//healthcheck,
  }
}
