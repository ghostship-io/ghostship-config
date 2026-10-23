# Webhook code is delivered through the private managed Nix store; the image
# contains only base utilities. The heartbeat /bin/cat has its own domain.
# No abstractions or explicit denies: unmatched operations must remain allowed
# and visible while this profile is in complain mode.
profile ghostship-hooks flags=(complain,attach_disconnected,mediate_deleted) {
  network inet stream,
  network inet6 stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-hooks,

  /nix/store/*-ghostship-hooks-entrypoint/bin/start rix,
  /nix/store/*-bash-*/bin/bash rix,
  /nix/store/*-bash-*/lib/** mr,
  /nix/store/*-python3-minimal-*/bin/python3* rix,
  /nix/store/*-coreutils-*/bin/cat cx -> tools,
  /bin/cat cx -> tools,
  # The interpreter's shared libraries and standard library.
  /nix/store/*/lib/** mr,
  /nix/store/*-ghostship-github-ingress/share/ghostship-github/ingress.py r,

  /dev/null rw,
  /dev/urandom r,
  /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf} r,

  /run/secrets/hooks.env r,

  /spool/ r,
  /spool/{,.}* rwl,

  # Deliberately audit the collector heartbeat read even when permitted.
  audit /proc/sys/kernel/random/boot_id r,

  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    # Audit heartbeat only: no spool, script or network access.
    /bin/cat rix,
    /nix/store/*-coreutils-*/bin/cat rix,
    /nix/store/*/lib/*.so* mr,
    /dev/null rw,
    audit /proc/sys/kernel/random/boot_id r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-hooks,
    signal (send, receive) peer=ghostship-hooks//tools,
  }
}
