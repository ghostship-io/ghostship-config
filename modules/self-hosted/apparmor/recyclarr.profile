# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# ghcr.io/recyclarr/recyclarr:8 (sha256:b1fbb929ba71..., built 2026-10-14),
# Alpine 3.24.2 musl; .NET runtime 10.0.13 at /usr/share/dotnet; app at
# /app/recyclarr. Runs as uid/gid 3000 with no effective capabilities, so no
# capability rules. No podman healthcheck.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Process map: tini (top) -> /entrypoint.sh (bash, top) writes /tmp/crontab
# and execs supercronic (cron). Once a day (CRON_SCHEDULE=@daily) supercronic
# runs `/bin/sh -c /cron.sh` (job: BusyBox sh + bash) which runs
# `recyclarr sync` (recyclarr: .NET). recyclarr runs `git status`,
# `git fetch --depth 1 <url>` and `git reset --hard FETCH_HEAD` on the
# TRaSH-guides/config-template clones (git, with git-remote-https).

@{rcy_net} = /usr/share/dotnet/shared/Microsoft.NETCore.App/10.0.13

profile ghostship-recyclarr flags=(complain,attach_disconnected,mediate_deleted) {
  /sbin/tini rix,
  # `#!/usr/bin/env bash`: env (BusyBox) is only mapped as interpreter here.
  /entrypoint.sh rix,
  /bin/busybox mr,
  /bin/bash rix,
  /usr/bin/supercronic cx -> cron,
  # RECYCLARR_CREATE_CONFIG=true path (`recyclarr config create`) or CLI args.
  /app/recyclarr/recyclarr px -> ghostship-recyclarr//recyclarr,
  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/{libncursesw.so.6.6,libreadline.so.8.3} mr,
  /tmp/ r,
  /tmp/crontab rw,
  /config/ r,
  /config/recyclarr.yml r,
  / r,
  /etc/{passwd,group} r,
  /dev/null rw,
  /dev/tty rw,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-recyclarr,
  signal (send) peer=ghostship-recyclarr//{cron,job,recyclarr,git},

  profile cron flags=(complain,attach_disconnected,mediate_deleted) {
    # supercronic: read the generated crontab, run jobs through /bin/sh.
    /usr/bin/supercronic mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /bin/busybox px -> ghostship-recyclarr//job,
    /tmp/ r,
    /tmp/crontab r,
    /etc/localtime r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/{cgroup,mountinfo,maps,stat,status} r,
    /sys/fs/cgroup/cpu.max r,
    /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-recyclarr,
    signal (send, receive) peer=ghostship-recyclarr//cron,
    signal (send) peer=ghostship-recyclarr//{job,recyclarr},
  }

  profile job flags=(complain,attach_disconnected,mediate_deleted) {
    # `/bin/sh -c /cron.sh`; cron.sh (`#!/usr/bin/env bash`) echoes a banner
    # with `date` and runs `recyclarr sync`.
    /bin/busybox rix,
    /cron.sh rix,
    /bin/bash rix,
    /app/recyclarr/recyclarr px -> ghostship-recyclarr//recyclarr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libncursesw.so.6.6,libreadline.so.8.3} mr,
    /etc/localtime r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/tty rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-recyclarr//cron,
    signal (send, receive) peer=ghostship-recyclarr//job,
    signal (send) peer=ghostship-recyclarr//recyclarr,
  }

  profile recyclarr flags=(complain,attach_disconnected,mediate_deleted) {
    # .NET apphost + shared runtime; config, state, logs and repo caches under
    # /config. Only git may be executed (CliWrap).
    /app/recyclarr/recyclarr mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libgcc_s.so.1,libstdc++.so.6.0.34} mr,
    # Runtime-dlopened system libraries: OpenSSL (TLS/crypto) and zlib.
    /usr/lib/{libssl.so.3,libcrypto.so.3,libz.so.1.3.2} mr,
    /usr/share/dotnet/ r,
    /usr/share/dotnet/host/fxr/ r,
    /usr/share/dotnet/host/fxr/10.0.13/ r,
    /usr/share/dotnet/host/fxr/10.0.13/libhostfxr.so mr,
    /usr/share/dotnet/shared/ r,
    /usr/share/dotnet/shared/Microsoft.NETCore.App/ r,
    @{rcy_net}/ r,
    @{rcy_net}/** r,
    @{rcy_net}/lib{hostpolicy,coreclr,clrjit,System.Native,System.Globalization.Native,System.IO.Compression.Native,System.Net.Security.Native,System.Security.Cryptography.Native.OpenSsl}.so mr,
    /app/recyclarr/ r,
    /app/recyclarr/** r,

    /usr/bin/git px -> ghostship-recyclarr//git,

    /config/ r,
    /config/{recyclarr.yml,settings.yml} r,
    /config/{configs,includes}/ r,
    /config/{configs,includes}/** r,
    /config/logs/ rw,
    /config/logs/** rw,
    /config/state/ rw,
    /config/state/** rwk,
    /config/resources/ rw,
    /config/resources/** rwk,
    /tmp/ r,
    /tmp/** rw,

    / r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,localtime,os-release} r,
    /etc/ssl/ r,
    /etc/ssl/{openssl.cnf,cert.pem} r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/** r,
    /usr/share/zoneinfo/ r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/tty rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/ r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{stat,status,maps,cgroup,mountinfo,mounts,cmdline,exe} r,
    /proc/{self,thread-self}/task/[0-9]*/{stat,comm} rw,
    /proc/{meminfo,cpuinfo,stat} r,
    /proc/sys/kernel/{osrelease,pid_max} r,
    /proc/sys/vm/overcommit_memory r,
    /sys/devices/system/cpu/ r,
    /sys/devices/system/cpu/{online,possible,present} r,
    /sys/devices/system/cpu/cpu[0-9]*/** r,
    /sys/fs/cgroup/ r,
    /sys/fs/cgroup/{cgroup.controllers,cpu.max,cpu.weight,cpuset.cpus.effective,memory.max,memory.high,memory.current,memory.stat,memory.swap.max} r,
    # Sonarr/Radarr APIs over HTTP(S); DNS.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-recyclarr//{job,cron},
    signal (receive) peer=ghostship-recyclarr,
    signal (send, receive) peer=ghostship-recyclarr//recyclarr,
    signal (send) peer=ghostship-recyclarr//git,
  }

  profile git flags=(complain,attach_disconnected,mediate_deleted) {
    # git status/fetch --depth 1/reset --hard inside the guide clones. git
    # re-execs itself (git-core links resolve to /usr/bin/git) and the HTTPS
    # remote helper. No hooks, editors, pagers or shells are allowed: hooks
    # live in the writable clones under /config.
    /usr/bin/git rix,
    /usr/libexec/git-core/ r,
    /usr/libexec/git-core/git-remote-http rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libpcre2-8.so.0.16.1,libz.so.1.3.2,libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libcares.so.2.19.7,libcrypto.so.3,libcurl.so.4.8.0,libidn2.so.0.4.0,libnghttp2.so.14.29.5,libpsl.so.5.3.5,libssl.so.3,libunistring.so.5.2.1,libzstd.so.1.5.7} mr,
    /usr/share/git-core/ r,
    /usr/share/git-core/** r,
    /config/ r,
    /config/resources/ rw,
    /config/resources/** rwkl,
    /tmp/ r,
    / r,
    /.gitconfig r,
    /.config/git/{config,attributes,ignore} r,
    /etc/{gitconfig,passwd,group,hosts,resolv.conf,nsswitch.conf,localtime} r,
    /etc/ssl/ r,
    /etc/ssl/{openssl.cnf,cert.pem} r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/** r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{stat,status} r,
    /proc/{cpuinfo,meminfo} r,
    /sys/devices/system/cpu/{online,possible,present} r,
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-recyclarr//recyclarr,
    signal (send, receive) peer=ghostship-recyclarr//git,
  }
}
