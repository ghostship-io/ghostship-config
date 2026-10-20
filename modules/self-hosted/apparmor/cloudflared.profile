# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/cloudflare/cloudflared:latest = cloudflared 2026.10.1 (image built
# 2026-10-15, distroless base-debian13 nonroot); uid/gid 3000:3000; no
# capabilities, no volume mounts, no healthcheck.
# The Internet ingress: a remotely managed tunnel (token in the environment;
# never in this file). QUIC/UDP and TCP to the Cloudflare edge, plain HTTP to
# origins on ghostship_net and ghostship_github_net, metrics on :20241.
# /usr/local/bin/cloudflared is a static Go binary started directly by the
# runtime (no init or shell), so the top profile is the server domain.
# The image has no shell and no /bin/cat: the collector's heartbeat probe
# cannot run in this container.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-cloudflared flags=(complain,attach_disconnected,mediate_deleted) {
  # No exec transitions at all: cloudflared never spawns helpers; with
  # --no-autoupdate it must not replace or re-exec itself.
  /usr/local/bin/cloudflared mr,

  # Go resolver and TLS trust (SSL_CERT_FILE names this bundle).
  /etc/{hosts,resolv.conf,nsswitch.conf} r,
  /etc/ssl/certs/ca-certificates.crt r,

  /dev/null rw,

  # Go runtime: cgroup CPU quota discovery (cpu.max is open in the live
  # process), huge page size, and listen backlog for the metrics listener.
  owner /proc/{self,thread-self,[0-9]*}/{cgroup,mountinfo} r,
  /sys/fs/cgroup/cpu.max r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
  /proc/sys/net/core/somaxconn r,
  # ICMP proxy checks whether its gid may open unprivileged ICMP sockets.
  /proc/sys/net/ipv4/ping_group_range r,

  # Edge connections (QUIC on UDP, HTTP/2 fallback on TCP), origin HTTP,
  # DNS, ICMP proxy datagram sockets and the metrics listener.
  # AppArmor socket rules cannot restrict destinations or ports.
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-cloudflared,

  # The heartbeat read, should a future image ship /bin/cat.
  audit /proc/sys/kernel/random/boot_id r,
}
