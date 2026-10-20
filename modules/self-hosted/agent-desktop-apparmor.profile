# Agent Desktop container: Podman's default container policy (see
# container-default-apparmor.profile) plus one permitted transition, into the
# confined desktop viewer below.
include <tunables/global>

profile ghostship-agent-desktop flags=(attach_disconnected,mediate_deleted) {
  include <abstractions/base>

  network,
  capability,
  file,
  umount,

  signal (receive) peer=unconfined,
  signal (send,receive) peer=ghostship-agent-desktop,
  signal (send) peer=ghostship-desktop-viewer,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}runc,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}crun*,
  signal (receive) peer={/usr/bin/,/usr/sbin/,}podman,

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
}

# The desktop viewer (/agents/ behind Cloudflare Access): a Python server that
# relays agent browser windows over loopback DevTools. It may read its own
# code and the run registry, write pause and activity markers there, and use
# the network (loopback DevTools; Cloudflare Access signing keys over HTTPS). Browser profiles, SSH keys, secrets and every executable are denied.
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
  signal (receive) peer=unconfined,
}
