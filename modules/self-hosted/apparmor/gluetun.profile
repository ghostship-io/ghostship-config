# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# qmcgaw/gluetun (docker.io/qmcgaw/gluetun:latest), commit 156ccc2 built
# 2026-10-19; Alpine 3.23.6 (musl). /gluetun-entrypoint is a static Go binary.
# Runs as uid 0 / gid 3000 with CapEff 0x800415fb (default set plus NET_ADMIN;
# no NET_RAW, so the ICMP health check falls back to DNS-over-UDP checks).
# VPN: the running process uses kernelspace WireGuard (tun0 is a wireguard
# link configured over generic netlink); no openvpn process runs. Firewall:
# iptables/ip6tables via xtables-nft-multi (nf_tables), conntrack/tcp/udp
# matches only. Built-in Go DNS server (no unbound), HTTP proxy on :8888,
# control server on :8000, health server on 127.0.0.1:9999, port forwarding
# with a `/bin/sh -c 'wget ...'` up/down command that updates qBittorrent.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions or includes: their implicit permissions would obscure this allowlist.

profile ghostship-gluetun flags=(complain,attach_disconnected,mediate_deleted) {
  # The daemon is entered by crun's change_onexec, not by an exec rule. Its
  # healthcheck subcommand (podman `sh -c "/gluetun-entrypoint healthcheck"`)
  # is exec'd from BusyBox sh and gets its own domain.
  /gluetun-entrypoint rm,
  /gluetun-entrypoint cx -> healthcheck,
  # BusyBox is the healthcheck's /bin/sh and the collector's /bin/cat (both
  # entered by podman exec, not by an exec rule). Gluetun itself execs it only
  # for the port-forwarding up/down command.
  /bin/busybox rm,
  /bin/busybox cx -> portforward,
  /lib/ld-musl-aarch64.so.1 mr,
  # iptables, ip6tables and their -nft/-restore/-save names all resolve here.
  /usr/sbin/xtables-nft-multi cx -> firewall,
  # Startup version banner only (`OpenVPN version: 2.6.20`); VPN_TYPE is
  # wireguard, so OpenVPN never runs a tunnel.
  /usr/sbin/openvpn2.6 cx -> openvpn,

  # Routes, rules, links and WireGuard over netlink; binding DNS on :53;
  # chown of /tmp/gluetun/forwarded_port to PUID/PGID 1000; root writes into
  # the uid-3000-owned /gluetun tree. No net_raw, sys_module, setuid or mknod.
  capability net_admin,
  capability net_bind_service,
  capability chown,
  capability dac_override,

  # Persistent state: servers/ data (UPDATER_PERIOD=24h rewrites it), PIA port
  # forwarding data, WireGuard key and server selection.
  /gluetun/ r,
  /gluetun/** rw,
  # PUBLICIP_FILE and VPN_PORT_FORWARDING_STATUS_FILE.
  /tmp/ r,
  /tmp/gluetun/ rw,
  /tmp/gluetun/{ip,forwarded_port} rw,
  # The local DNS server replaces the nameserver; PUID/PGID account setup.
  /etc/resolv.conf rw,
  /etc/{passwd,group} rw,
  /etc/{hosts,nsswitch.conf,services,protocols,alpine-release} r,
  /etc/ssl/certs/ r,
  /etc/ssl/certs/ca-certificates.crt r,
  /usr/share/zoneinfo/** r,
  /dev/null rw,
  /dev/urandom r,
  /dev/net/tun rw,

  # Go runtime: cgroup CPU quota (cpu.max is held open), THP size, somaxconn.
  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo} r,
  /sys/fs/cgroup/cpu.max r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
  /proc/sys/net/core/somaxconn r,
  # Collector heartbeat: `podman exec <c> /bin/cat` (BusyBox) lands here.
  audit /proc/sys/kernel/random/boot_id r,

  # VPN endpoint over UDP, DNS server [::]:53 (UDP+TCP) and plain upstream,
  # HTTP proxy/control/health listeners, DNS block-list, public-IP and
  # updater HTTPS, IPv6 reachability probes; NETLINK_ROUTE and
  # NETLINK_GENERIC (wireguard) are SOCK_RAW. No inet raw (ICMP is unavailable
  # without NET_RAW). AppArmor cannot restrict destinations or ports.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  network netlink raw,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-gluetun,
  signal (send) peer=ghostship-gluetun//firewall,
  signal (send) peer=ghostship-gluetun//portforward,
  signal (send) peer=ghostship-gluetun//openvpn,
  signal (send) peer=ghostship-gluetun//healthcheck,

  # xtables-nft-multi programs nf_tables over NETLINK_NETFILTER. It loads only
  # the extensions used by the observed rule set (-j ACCEPT/DROP, conntrack
  # --ctstate, -p tcp/udp --dport). Legacy xtables is not used.
  profile firewall flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/sbin/xtables-nft-multi rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{mnl.so.0.2.0,nftnl.so.11.6.0,xtables.so.12.7.0} mr,
    /usr/lib/xtables/ r,
    /usr/lib/xtables/libxt_{standard,conntrack,tcp,udp}.so mr,
    /etc/{protocols,services} r,
    /dev/null rw,
    capability net_admin,
    network netlink raw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-gluetun,
    signal (send, receive) peer=ghostship-gluetun//firewall,
  }

  # VPN_PORT_FORWARDING_{UP,DOWN}_COMMAND: BusyBox sh runs GNU wget, which
  # POSTs the forwarded port to qBittorrent's Web API on 127.0.0.1:5000 (the
  # shared network namespace) and writes the response to stdout. No /gluetun,
  # no /tmp/gluetun, no capabilities.
  profile portforward flags=(complain,attach_disconnected,mediate_deleted) {
    /bin/busybox rix,
    /usr/bin/wget rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{crypto.so.3,ssl.so.3,idn2.so.0.4.0,pcre2-8.so.0.16.1,unistring.so.5.2.1,z.so.1.3.2} mr,
    /etc/wgetrc r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,services} r,
    /dev/null rw,
    network inet stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-gluetun,
    signal (send, receive) peer=ghostship-gluetun//portforward,
  }

  # `gluetun-entrypoint healthcheck`: one HTTP GET to the health server on
  # 127.0.0.1:9999. No state files, no capabilities beyond the TCP client.
  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    /gluetun-entrypoint rm,
    owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo} r,
    /sys/fs/cgroup/cpu.max r,
    /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    network inet stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-gluetun,
    signal (send, receive) peer=ghostship-gluetun//healthcheck,
  }

  # `openvpn2.6 --version` at startup: prints and exits. No network, no tun,
  # no configuration or credentials.
  profile openvpn flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/sbin/openvpn2.6 rm,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/lib{cap-ng.so.0.0.0,crypto.so.3,ssl.so.3,lz4.so.1.10.0,lzo2.so.2.0.0} mr,
    /etc/ssl/openssl.cnf r,
    /dev/null rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-gluetun,
    signal (send, receive) peer=ghostship-gluetun//openvpn,
  }
}
