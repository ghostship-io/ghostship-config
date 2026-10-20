# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# localhost/ghostship-github-coordinator:z36h732xfvk6bxc6fzamr37s0c1q8dap, this
# repository's Nix image (github-engineering.nix): stdlib CPython 3.13.12 plus
# websockets 15.0.1 running `python3 -B -m ghostship_github.coordinator`.
# uid 62031, gid 62032 (+62031); --cap-drop=ALL, no-new-privileges, read-only
# root, /tmp tmpfs noexec. The image has no shell or coreutils.
# Flat profile: under no_new_privs AppArmor never enters a cx child, so there
# are no children and no transitions. The coordinator spawns nothing: the
# ghostship_t3 bridge's `t3 auth session issue` fallback only runs when the
# mounted token is unreadable, and no t3 binary exists in the image.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
profile ghostship-github-coordinator flags=(complain,attach_disconnected,mediate_deleted) {
  network inet stream,
  network inet6 stream,
  # Resolver queries for api.github.com, T3 and ntfy.
  network inet dgram,
  network inet6 dgram,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-github-coordinator,

  # Interpreter (entered via the python3-3.13.12-env bin/python3 symlink).
  # Only store hashes are globbed: an image rebuild that changes a version
  # requires review.
  /nix/store/*-python3-3.13.12/bin/python3.13 rix,
  /nix/store/*-python3-3.13.12-env/{,**} r,
  /nix/store/*-python3-3.13.12/lib/libpython3.13.so.1.0 mr,
  /nix/store/*-python3-3.13.12/lib/python3.13/{,**} r,
  /nix/store/*-python3-3.13.12/lib/python3.13/lib-dynload/*.cpython-313-aarch64-linux-gnu.so mr,
  /nix/store/*-python3.13-websockets-15.0.1/lib/python3.13/site-packages/{,**} r,
  /nix/store/*-python3.13-websockets-15.0.1/lib/python3.13/site-packages/websockets/speedups.cpython-313-aarch64-linux-gnu.so mr,
  # Loaded libraries (live maps) and the stdlib extensions' other dependencies.
  /nix/store/*-glibc-2.40-224/lib/{ld-linux-aarch64.so.1,libc.so.6,libdl.so.2,libm.so.6,libpthread.so.0,libresolv.so.2,libnss_dns.so.2,libnss_files.so.2} mr,
  /nix/store/*-glibc-2.40-224/lib/locale/C.utf8/{,**} r,
  /nix/store/*-gcc-14.3.0-libgcc/lib/libgcc_s.so.1 mr,
  /nix/store/*-openssl-3.6.2/lib/{libcrypto.so.3,libssl.so.3} mr,
  /nix/store/*-sqlite-3.50.4/lib/libsqlite3.so.3.50.4 mr,
  /nix/store/*-zlib-1.3.2/lib/libz.so.1.3.2 mr,
  /nix/store/*-bzip2-1.0.8/lib/libbz2.so.1.0.8 mr,
  /nix/store/*-xz-5.8.3/lib/liblzma.so.5.8.3 mr,
  /nix/store/*-util-linux-minimal-2.41.4-lib/lib/libuuid.so.1.3.0 mr,
  /nix/store/*-libffi-3.5.2/lib/libffi.so.8.2.0 mr,
  /nix/store/*-expat-2.7.5/lib/libexpat.so.1.11.3 mr,
  /nix/store/*-mpdecimal-4.0.1/lib/libmpdec.so.4.0.1 mr,
  /nix/store/*-openssl-3.6.2/etc/ssl/openssl.cnf r,
  /nix/store/*-nss-cacert-3.123/etc/ssl/certs/ca-bundle.crt r,
  /nix/store/*-tzdata-2026a/share/zoneinfo/{,**} r,
  /nix/store/*-mailcap-2.1.54/etc/mime.types r,

  # Coordinator code (PYTHONPATH).
  /nix/store/*-ghostship-github-coordinator/share/ghostship-github/python/{,**} r,

  /etc/{passwd,group,hosts,resolv.conf,hostname,nsswitch.conf,localtime} r,
  /etc/ssl/certs/ca-bundle.crt r,
  /etc/ghostship-github/config.json r,
  /run/secrets/github.env r,
  /run/ghostship-integrations/ r,
  /run/ghostship-integrations/{t3-token,t3-server.json} r,
  /dev/null rw,
  /dev/urandom r,
  /proc/{self,thread-self}/fd/ r,

  # Webhook pointers and host incidents: read, then remove.
  /spool/ r,
  /spool/*.json rw,
  /incidents/ r,
  /incidents/*.json rw,
  # SQLite state with its WAL, shared-memory and journal files.
  /state/ r,
  /state/github.sqlite{,-wal,-shm,-journal} rwk,
  /tmp/ r,
  owner /tmp/** rw,
  /var/tmp/ r,

  # Heartbeat open for the AppArmor review (the image has no /bin/cat).
  audit /proc/sys/kernel/random/boot_id r,
}
