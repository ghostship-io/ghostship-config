# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# ghcr.io/journeydocker/plex-auto-languages:latest (sha256:51224217f7a0...),
# Alpine 3.24.2 musl; CPython 3.14.8 (/usr/local) with venv /opt/venv; app
# /app/main.py. Runs as uid/gid 3000 with no effective capabilities, so no
# capability rules.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Domains: top = /sbin/tini and the podman healthcheck's `sh -c` (BusyBox);
# python = `python main.py -c /config/config.yaml`; healthcheck = the
# healthcheck's `pgrep -f main.py` (BusyBox applet).

@{pal_py} = /usr/local/lib/python3.14
@{pal_sp} = /opt/venv/lib/python3.14/site-packages
# Standard-library extension modules mapped by the live process.
@{pal_dynload} = array _asyncio binascii _bisect _blake2 _bz2 _codecs_cn _codecs_hk _codecs_iso2022 _codecs_jp _codecs_kr _codecs_tw _ctypes _decimal _elementtree fcntl grp _hashlib _heapq _hmac _interpreters _json _lzma math _multibytecodec _pickle _posixsubprocess pyexpat _queue _random select _socket _sqlite3 _ssl _struct termios unicodedata _uuid zlib _zoneinfo _zstd

profile ghostship-plex-auto-languages flags=(complain,attach_disconnected,mediate_deleted) {
  /sbin/tini rix,
  # CMD `python` resolves via PATH to /opt/venv/bin/python -> /usr/local/bin/python3.14.
  /usr/local/bin/python3.14 cx -> python,
  # The healthcheck shell runs here (crun onexec); its pgrep moves out.
  /bin/busybox mr,
  /bin/busybox cx -> healthcheck,
  /lib/ld-musl-aarch64.so.1 mr,
  / r,
  /dev/null rw,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  audit /proc/sys/kernel/random/boot_id r,
  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-plex-auto-languages,
  signal (send) peer=ghostship-plex-auto-languages//{python,healthcheck},

  profile python flags=(complain,attach_disconnected,mediate_deleted) {
    # Image code is root-owned and read-only; no exec permissions at all.
    /usr/local/bin/python3.14 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/local/lib/libpython3.14.so.1.0 mr,
    /usr/lib/{libbz2.so.1.0.8,libcrypto.so.3,libffi.so.8.2.0,liblzma.so.5.8.4,libsqlite3.so.3.53.4,libssl.so.3,libuuid.so.1.3.0,libz.so.1.3.2,libzstd.so.1.5.7} mr,
    @{pal_py}/lib-dynload/@{pal_dynload}.cpython-314-aarch64-linux-musl.so mr,
    @{pal_sp}/{charset_normalizer/cd,charset_normalizer/md,markupsafe/_speedups,yaml/_yaml}.cpython-314-aarch64-linux-musl.so mr,
    @{pal_py}/ r,
    @{pal_py}/** r,
    /opt/venv/ r,
    /opt/venv/pyvenv.cfg r,
    /opt/venv/bin/ r,
    /opt/venv/lib/ r,
    /opt/venv/lib/python3.14/ r,
    @{pal_sp}/ r,
    @{pal_sp}/** r,
    /app/ r,
    /app/main.py r,
    /app/config/default.yaml r,
    /app/plex_auto_languages/ r,
    /app/plex_auto_languages/** r,

    # User config (read), cache database (SQLite WAL) and rotating log.
    /config/ r,
    /config/config.yaml r,
    /config/cache/ rw,
    /config/cache/*.sqlite3{,-wal,-shm,-journal} rwk,
    /config/cache/*.json r,
    /config/cache/*.json.migrated rw,
    /logs/ rw,
    /logs/plex_auto_languages.log rw,
    /logs/plex_auto_languages.log.{1,2,3,4,5,6,7,8,9,10} rw,
    /tmp/ r,

    / r,
    /etc/{passwd,group,hosts,resolv.conf,nsswitch.conf,localtime,os-release,mime.types} r,
    /etc/ssl/ r,
    /etc/ssl/{openssl.cnf,cert.pem} r,
    /etc/ssl/certs/ r,
    /etc/ssl/certs/** r,
    /usr/share/zoneinfo/ r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdout,stderr} rw,
    /proc/{self,thread-self}/fd/ r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{self,thread-self}/{stat,status,maps} r,
    # Plex HTTP + alert websocket, notifications, health server on :9880, DNS.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-plex-auto-languages,
    signal (send, receive) peer=ghostship-plex-auto-languages//python,
  }

  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    # `pgrep -f main.py`: scan /proc command lines. No files, no network.
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /proc/ r,
    /proc/[0-9]*/{cmdline,stat,status} r,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-plex-auto-languages,
    signal (send, receive) peer=ghostship-plex-auto-languages//healthcheck,
  }
}
