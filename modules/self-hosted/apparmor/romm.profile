# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# docker.io/rommapp/romm:latest (RomM 5.4.0, image sha256:03295f95a629...,
# built 2026-10-10); Alpine 3.24.2, musl; CPython 3.14.7 (/usr/local) with
# the uv venv /src/.venv; nginx 1.30.5; valkey 9.0.4. Runs as uid/gid 3000
# with no effective capabilities, so no capability rules are granted.
# Load by name through the container runtime; there is no host attachment glob.
# Keep complain until daily review records seven observed days without changes.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
#
# Process map (from /init, the bash supervisor loop):
#   top        /docker-entrypoint.sh and /init (bash), plus the podman
#              healthcheck's `sh -c` (BusyBox) which crun starts here.
#   tools      every BusyBox applet: startup helpers (cut, grep, cp, sed,
#              mkdir, rm, cat, date), the 5 s watchdog `sleep`, and the
#              healthcheck's `wget --spider http://127.0.0.1:8080/`.
#   templates  /docker-entrypoint.d/20-envsubst-on-templates.sh + envsubst,
#              the only domain that writes nginx configuration.
#   startup    `python3 -c` banner/secret, `alembic upgrade head`,
#              `python3 /backend/startup.py` (one-shot, before the daemons).
#   api        gunicorn + uvicorn workers (127.0.0.1-reachable :5000).
#   worker     `rq cron` and the three `rq worker` processes and work horses.
#   valkey     internal valkey-server --dir /redis-data.
#   nginx      nginx master + workers serving :8080.
#   archive, rahasher, converto, patcher: helper executables spawned by
#              api/worker for 7zz/bsdtar, RAHasher, rom-converto and node.
# The image code (/backend, /src/.venv, /usr/local/lib/python3.14) is
# root-owned and not writable by uid 3000; no domain may execute from the
# writable mounts (/romm/*, /redis-data) or /tmp.

@{romm_py} = /usr/local/lib/python3.14
@{romm_sp} = /src/.venv/lib/python3.14/site-packages
# Standard-library extension modules shipped by the image, excluding the
# _test*/xx* modules, Tk and curses. The set used depends on the code path.
@{romm_dynload} = array _asyncio binascii _bisect _blake2 _bz2 cmath _codecs_cn _codecs_hk _codecs_iso2022 _codecs_jp _codecs_kr _codecs_tw _csv _ctypes _dbm _decimal _elementtree fcntl _gdbm grp _hashlib _heapq _hmac _interpchannels _interpqueues _interpreters _json _lsprof _lzma math _md5 mmap _multibytecodec _multiprocessing _pickle _posixshmem _posixsubprocess pyexpat _queue _random resource select _sha1 _sha2 _sha3 _socket _sqlite3 _ssl _statistics _struct syslog termios unicodedata _uuid zlib _zoneinfo _zstd
# Native venv extensions (exact files). Excluded: psycopg_c (no PostgreSQL;
# DB is MariaDB), grpc (OpenTelemetry is disabled), PIL/_imagingtk.
@{romm_sp_so} = aiohttp/_http_parser.cpython-314-aarch64-linux-musl.so aiohttp/_http_writer.cpython-314-aarch64-linux-musl.so aiohttp/_websocket/mask.cpython-314-aarch64-linux-musl.so aiohttp/_websocket/reader_c.cpython-314-aarch64-linux-musl.so bcrypt/_bcrypt.abi3.so bcrypt.libs/libgcc_s-2d945d6c.so.1 _cffi_backend.cpython-314-aarch64-linux-musl.so charset_normalizer/md.cpython-314-aarch64-linux-musl.so charset_normalizer/md__mypyc.cpython-314-aarch64-linux-musl.so cryptography/hazmat/bindings/_rust.abi3.so cryptography.libs/libgcc_s-2d945d6c.so.1 frozenlist/_frozenlist.cpython-314-aarch64-linux-musl.so httptools/parser/parser.cpython-314-aarch64-linux-musl.so httptools/parser/url_parser.cpython-314-aarch64-linux-musl.so inflate64/_inflate64.cpython-314-aarch64-linux-musl.so mariadb/_mariadb.cpython-314-aarch64-linux-musl.so markupsafe/_speedups.cpython-314-aarch64-linux-musl.so multidict/_multidict.cpython-314-aarch64-linux-musl.so propcache/_helpers_c.cpython-314-aarch64-linux-musl.so pydantic_core/_pydantic_core.cpython-314-aarch64-linux-musl.so pydantic_core.libs/libgcc_s-0bf60adc.so.1 sigil/_sigil.cpython-314-aarch64-linux-musl.so streaming_form_data/_parser.cpython-314-aarch64-linux-musl.so uvloop/loop.cpython-314-aarch64-linux-musl.so watchfiles/_rust_notify.abi3.so watchfiles.libs/libgcc_s-0bf60adc.so.1 websockets/speedups.cpython-314-aarch64-linux-musl.so wrapt/_wrappers.cpython-314-aarch64-linux-musl.so yaml/_yaml.cpython-314-aarch64-linux-musl.so yarl/_quoting_c.cpython-314-aarch64-linux-musl.so
@{romm_sp_so} += sqlalchemy/engine/_processors_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/engine/_result_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/engine/_row_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/engine/_util_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/sql/_cache_key_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/sql/_util_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/util/_collections_cy.cpython-314-aarch64-linux-musl.so sqlalchemy/util/_immutabledict_cy.cpython-314-aarch64-linux-musl.so
@{romm_sp_so} += PIL/_avif.cpython-314-aarch64-linux-musl.so PIL/_imagingcms.cpython-314-aarch64-linux-musl.so PIL/_imaging.cpython-314-aarch64-linux-musl.so PIL/_imagingft.cpython-314-aarch64-linux-musl.so PIL/_imagingmath.cpython-314-aarch64-linux-musl.so PIL/_imagingmorph.cpython-314-aarch64-linux-musl.so PIL/_webp.cpython-314-aarch64-linux-musl.so
@{romm_sp_so} += pillow.libs/libavif-de6ae66a.so.16.4.2 pillow.libs/libbrotlicommon-eeb6122a.so.1.2.0 pillow.libs/libbrotlidec-e44823e6.so.1.2.0 pillow.libs/libbsd-6304e545.so.0.12.2 pillow.libs/libfreetype-3a66a59f.so.6.20.6 pillow.libs/libharfbuzz-84d7f213.so.0.61421.0 pillow.libs/libjpeg-070e4618.so.62.4.0 pillow.libs/liblcms2-bde4aa14.so.2.0.19 pillow.libs/liblzma-1c3b7648.so.5.8.3 pillow.libs/libmd-e6555b27.so.0.1.0 pillow.libs/libopenjp2-2adb8702.so.2.5.4 pillow.libs/libpng16-207a4bf9.so.16.58.0 pillow.libs/libsharpyuv-2dcb7e33.so.0.1.2 pillow.libs/libtiff-29851ca2.so.6.2.0 pillow.libs/libwebp-3d8de41b.so.7.2.0 pillow.libs/libwebpdemux-bb297809.so.2.0.17 pillow.libs/libwebpmux-0fa611d6.so.3.1.2 pillow.libs/libXau-541039f7.so.6.0.0 pillow.libs/libxcb-b62355a5.so.1.1.0 pillow.libs/libXdmcp-f7925934.so.6.0.0 pillow.libs/libzstd-65db3951.so.1.5.7
# System libraries mapped by the live Python processes (on-disk names) plus
# their resolved dependencies (libmagic is dlopened by python-magic).
@{romm_py_libs} = libbz2.so.1 libcrypto.so.3 libffi.so.8 liblzma.so.5 libssl.so.3 libuuid.so.1 libz.so.1 libzstd.so.1 libmariadb.so.3 libmagic.so.1.0.0

profile ghostship-romm flags=(complain,attach_disconnected,mediate_deleted) {
  # Entrypoint scripts; `#!/usr/bin/env bash` needs BusyBox (env) mapped here,
  # which then execs /bin/bash. Script reads also allow bash to interpret them.
  /docker-entrypoint.sh rix,
  /init rix,
  /bin/bash rix,
  /bin/busybox mr,
  /lib/ld-musl-aarch64.so.1 mr,
  /usr/lib/{libncursesw.so.6,libreadline.so.8} mr,

  # Every other BusyBox invocation (applets, watchdog sleep, healthcheck wget).
  /bin/busybox cx -> tools,
  /docker-entrypoint.d/20-envsubst-on-templates.sh cx -> templates,
  # PATH resolves python3/alembic/gunicorn/rq to the venv; the venv's python
  # symlinks to /usr/local/bin/python3. Script names select the daemon domain.
  /usr/local/bin/python3 cx -> startup,
  /src/.venv/bin/alembic cx -> startup,
  /src/.venv/bin/gunicorn cx -> api,
  /src/.venv/bin/rq cx -> worker,
  /usr/bin/valkey-server cx -> valkey,
  /usr/sbin/nginx cx -> nginx,

  # The supervisor loop writes/reads pid files and probes /proc/<pid>.
  /tmp/ r,
  /tmp/{valkey-server,gunicorn,rq_cron,rq_worker,rq_scan_worker,rq_streaming_worker,watcher,sync_watcher,nginx}.pid rw,
  /proc/ r,
  /proc/[0-9]*/ r,
  /backend/ r,
  / r,
  /dev/null rw,
  /dev/tty rw,
  /dev/{stdin,stdout,stderr} rw,
  /proc/{self,thread-self}/fd/[0-9]* rw,
  /etc/{passwd,group,hosts,resolv.conf} r,
  # Diagnostics heartbeat probe (collector) without widening any app domain.
  audit /proc/sys/kernel/random/boot_id r,
  # bash `echo >/dev/tcp/127.0.0.1/{6379,5000}` readiness probes.
  network inet stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-romm,
  signal (send) peer=ghostship-romm//{tools,templates,startup,api,worker,valkey,nginx},

  profile tools flags=(complain,attach_disconnected,mediate_deleted) {
    # BusyBox includes a shell; AppArmor cannot select applets by argv. This
    # domain gets no app code, data mounts, or exec transitions out.
    /bin/busybox rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /dev/null rw,
    /dev/{stdin,stdout,stderr} rw,
    # start_bin_gunicorn: mkdir/cp/sed -i of the logging config, and the
    # supervisor's `rm -f /tmp/*.pid` and `cat /tmp/<name>.pid`.
    /etc/gunicorn/logging.conf r,
    /tmp/ r,
    /tmp/gunicorn/ rw,
    /tmp/gunicorn/* rw,
    /tmp/*.pid rw,
    /etc/localtime r,
    /usr/share/zoneinfo/** r,
    /etc/{passwd,group,hosts,resolv.conf} r,
    audit /proc/sys/kernel/random/boot_id r,
    # Healthcheck: wget --spider http://127.0.0.1:8080/.
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//tools,
  }

  profile templates flags=(complain,attach_disconnected,mediate_deleted) {
    # nginx's envsubst-on-templates: read the image template, write conf.d.
    /docker-entrypoint.d/20-envsubst-on-templates.sh r,
    /bin/busybox rix,
    /usr/bin/envsubst rix,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/libintl.so.8.4.6 mr,
    /etc/nginx/templates/ r,
    /etc/nginx/templates/default.conf.template r,
    /etc/nginx/conf.d/ rw,
    /etc/nginx/conf.d/default.conf rw,
    /dev/null rw,
    /dev/{stdout,stderr} rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//templates,
  }

  profile startup flags=(complain,attach_disconnected,mediate_deleted) {
    # One-shot Python: banner, secret generation, alembic migrations and
    # /backend/startup.py (DB/valkey seeding and task enqueueing). No execs.
    /src/.venv/bin/alembic r,
    /usr/local/bin/python3 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/local/lib/libpython3.14.so.1.0 mr,
    /usr/lib/@{romm_py_libs} mr,
    @{romm_py}/lib-dynload/@{romm_dynload}.cpython-314-aarch64-linux-musl.so mr,
    @{romm_sp}/@{romm_sp_so} mr,
    @{romm_py}/ r,
    @{romm_py}/** r,
    /src/.venv/ r,
    /src/.venv/pyvenv.cfg r,
    /src/.venv/lib/ r,
    /src/.venv/lib/python3.14/ r,
    @{romm_sp}/ r,
    @{romm_sp}/** r,
    /backend/ r,
    /backend/** r,
    /usr/share/misc/magic.mgc r,
    /romm/ r,
    /romm/config/ r,
    /romm/config/config.yml rw,
    /romm/resources/ r,
    /romm/assets/ r,
    /tmp/ r,
    / r,
    /etc/{passwd,group,hosts,resolv.conf,localtime,os-release} r,
    /etc/ssl/{openssl.cnf,certs/ca-certificates.crt} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdin,stdout,stderr} rw,
    /proc/{self,thread-self}/{stat,status,maps,fd/} r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    # MariaDB (romm-db) and valkey over TCP; DNS for the DB host.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//startup,
  }

  profile api flags=(complain,attach_disconnected,mediate_deleted) {
    # gunicorn master + forked uvicorn workers. Helper executables move to
    # their own sibling domains; no shell, Python re-exec, or generic exec.
    /src/.venv/bin/gunicorn r,
    /usr/local/bin/python3 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/local/lib/libpython3.14.so.1.0 mr,
    /usr/lib/@{romm_py_libs} mr,
    @{romm_py}/lib-dynload/@{romm_dynload}.cpython-314-aarch64-linux-musl.so mr,
    @{romm_sp}/@{romm_sp_so} mr,
    @{romm_py}/ r,
    @{romm_py}/** r,
    /src/.venv/ r,
    /src/.venv/pyvenv.cfg r,
    /src/.venv/lib/ r,
    /src/.venv/lib/python3.14/ r,
    @{romm_sp}/ r,
    @{romm_sp}/** r,
    /backend/ r,
    /backend/** r,
    /usr/share/misc/magic.mgc r,

    /usr/bin/{7zz,bsdtar} px -> ghostship-romm//archive,
    /usr/bin/RAHasher px -> ghostship-romm//rahasher,
    /usr/bin/rom-converto px -> ghostship-romm//converto,
    /usr/bin/node px -> ghostship-romm//patcher,

    # RomM manages these mounts: uploads/deletes ROMs, saves/states/screens,
    # cover art and the UI-editable config.yml.
    /romm/ r,
    /romm/library/ rw,
    /romm/library/** rwk,
    /romm/assets/ rw,
    /romm/assets/** rwk,
    /romm/resources/ rw,
    /romm/resources/** rwk,
    /romm/config/ r,
    /romm/config/config.yml rw,
    # Worker heartbeat files (/tmp/wgunicorn-*), pid file, logging config,
    # the /tmp/romm cache and tempfile staging (patches, uploads).
    /tmp/ r,
    /tmp/gunicorn.pid rw,
    /tmp/gunicorn/logging.conf r,
    /tmp/wgunicorn-* rw,
    /tmp/romm/ rw,
    /tmp/romm/** rwk,
    /tmp/tmp*/ rw,
    /tmp/tmp*/** rw,
    /tmp/tmp* rw,
    /dev/shm/ r,
    /dev/shm/sem.mp-* rw,

    / r,
    /etc/{passwd,group,hosts,resolv.conf,localtime,os-release} r,
    /etc/ssl/{openssl.cnf,certs/ca-certificates.crt} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdin,stdout,stderr} rw,
    /proc/{self,thread-self}/{stat,status,maps,fd/} r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    # Listens on :5000 (nginx upstream); MariaDB, valkey and metadata APIs
    # (IGDB, ScreenScraper, RetroAchievements, SteamGridDB) over TCP; DNS.
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//api,
    signal (send) peer=ghostship-romm//{archive,rahasher,converto,patcher},
  }

  profile worker flags=(complain,attach_disconnected,mediate_deleted) {
    # rq cron + rq workers and their forked work horses (scans, metadata,
    # cleanup, conversions). Same code and data scope as the API.
    /src/.venv/bin/rq r,
    /usr/local/bin/python3 mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/local/lib/libpython3.14.so.1.0 mr,
    /usr/lib/@{romm_py_libs} mr,
    @{romm_py}/lib-dynload/@{romm_dynload}.cpython-314-aarch64-linux-musl.so mr,
    @{romm_sp}/@{romm_sp_so} mr,
    @{romm_py}/ r,
    @{romm_py}/** r,
    /src/.venv/ r,
    /src/.venv/pyvenv.cfg r,
    /src/.venv/lib/ r,
    /src/.venv/lib/python3.14/ r,
    @{romm_sp}/ r,
    @{romm_sp}/** r,
    /backend/ r,
    /backend/** r,
    /usr/share/misc/magic.mgc r,

    /usr/bin/{7zz,bsdtar} px -> ghostship-romm//archive,
    /usr/bin/RAHasher px -> ghostship-romm//rahasher,
    /usr/bin/rom-converto px -> ghostship-romm//converto,
    /usr/bin/node px -> ghostship-romm//patcher,

    /romm/ r,
    /romm/library/ rw,
    /romm/library/** rwk,
    /romm/assets/ rw,
    /romm/assets/** rwk,
    /romm/resources/ rw,
    /romm/resources/** rwk,
    /romm/config/ r,
    /romm/config/config.yml rw,
    /tmp/ r,
    /tmp/romm/ rw,
    /tmp/romm/** rwk,
    /tmp/tmp*/ rw,
    /tmp/tmp*/** rw,
    /tmp/tmp* rw,
    /tmp/{romm_rahasher_,rom-converto-}*/ rw,
    /tmp/{romm_rahasher_,rom-converto-}*/** rw,
    /dev/shm/ r,
    /dev/shm/sem.mp-* rw,

    / r,
    /etc/{passwd,group,hosts,resolv.conf,localtime,os-release} r,
    /etc/ssl/{openssl.cnf,certs/ca-certificates.crt} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/{random,urandom} r,
    /dev/{stdin,stdout,stderr} rw,
    /proc/{self,thread-self}/{stat,status,maps,fd/} r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    network inet stream,
    network inet6 stream,
    network inet dgram,
    network inet6 dgram,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//worker,
    signal (send) peer=ghostship-romm//{archive,rahasher,converto,patcher},
  }

  profile valkey flags=(complain,attach_disconnected,mediate_deleted) {
    # Internal cache/queue; snapshots to /redis-data (dump.rdb + temp files).
    /usr/bin/valkey-server mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /redis-data/ rw,
    /redis-data/dump.rdb rw,
    /redis-data/temp-*.rdb rw,
    /dev/null rw,
    /dev/urandom r,
    /etc/localtime r,
    /proc/sys/vm/overcommit_memory r,
    /proc/sys/net/core/somaxconn r,
    /sys/kernel/mm/transparent_hugepage/enabled r,
    /proc/{self,thread-self}/{stat,smaps} r,
    # Listens on *:6379 (IPv4 and IPv6).
    network inet stream,
    network inet6 stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//valkey,
  }

  profile nginx flags=(complain,attach_disconnected,mediate_deleted) {
    # Static frontend, X-Accel internal /library/ and /cache/ aliases, and the
    # reverse proxy to gunicorn. Read-only except its /tmp scratch dirs.
    /usr/sbin/nginx mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libcrypto.so.3,libssl.so.3,libz.so.1,libpcre2-8.so.0.16.1,liblzma.so.5,libxml2.so.2.13.9} mr,
    /usr/lib/nginx/modules/{ngx_http_js_module,ngx_http_zip_module}.so mr,
    /etc/nginx/ r,
    /etc/nginx/{nginx.conf,mime.types} r,
    /etc/nginx/conf.d/ r,
    /etc/nginx/conf.d/default.conf r,
    /etc/nginx/js/decode.js r,
    /var/www/html/ r,
    /var/www/html/** r,
    /romm/resources/ r,
    /romm/resources/** r,
    /romm/library/ r,
    /romm/library/** r,
    /tmp/romm/cache/ r,
    /tmp/romm/cache/** r,
    /tmp/nginx.pid rw,
    /tmp/{client_body,fastcgi,proxy,uwsgi,scgi}/ rw,
    /tmp/{client_body,fastcgi,proxy,uwsgi,scgi}/** rw,
    /etc/{passwd,group,hosts,resolv.conf,localtime} r,
    /usr/share/zoneinfo/** r,
    /dev/null rw,
    /dev/zero rw,
    /dev/urandom r,
    /dev/{stdout,stderr} rw,
    /var/log/nginx/error.log w,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /sys/devices/system/cpu/{online,possible} r,
    # :8080 on IPv4/IPv6, upstream 127.0.0.1:5000; master/worker channels.
    network inet stream,
    network inet6 stream,
    network unix stream,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm,
    signal (send, receive) peer=ghostship-romm//nginx,
  }

  profile archive flags=(complain,attach_disconnected,mediate_deleted) {
    # 7zz (7z/zip) and bsdtar (RAR): list/stream members from the library
    # into temporary staging. No network, no exec.
    /usr/bin/{7zz,bsdtar} mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libgcc_s.so.1,libstdc++.so.6.0.34} mr,
    /usr/lib/{libacl.so.1.1.2302,libbz2.so.1,libcrypto.so.3,libexpat.so.1.12.5,liblz4.so.1.10.0,liblzma.so.5,libz.so.1,libzstd.so.1} mr,
    /romm/library/ r,
    /romm/library/** r,
    /tmp/ r,
    /tmp/romm/ rw,
    /tmp/romm/** rw,
    /tmp/tmp*/ rw,
    /tmp/tmp*/** rw,
    /tmp/{romm_rahasher_,rom-converto-}*/ rw,
    /tmp/{romm_rahasher_,rom-converto-}*/** rw,
    /dev/null rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /sys/devices/system/cpu/{online,possible} r,
    /proc/{meminfo,cpuinfo} r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm//{api,worker},
  }

  profile rahasher flags=(complain,attach_disconnected,mediate_deleted) {
    # RetroAchievements hashing of a single ROM path. No network, no exec.
    /usr/bin/RAHasher mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /romm/library/ r,
    /romm/library/** r,
    /tmp/ r,
    /tmp/romm_rahasher_*/ r,
    /tmp/romm_rahasher_*/** r,
    /dev/null rw,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm//{api,worker},
  }

  profile converto flags=(complain,attach_disconnected,mediate_deleted) {
    # Static rom-converto: reads a library ROM, writes into its sandbox /
    # the conversion cache. No network, no exec.
    /usr/bin/rom-converto mr,
    /romm/library/ r,
    /romm/library/** r,
    /tmp/ r,
    /tmp/rom-converto-*/ rw,
    /tmp/rom-converto-*/** rw,
    /tmp/romm/cache/converts/ rw,
    /tmp/romm/cache/converts/** rw,
    /dev/null rw,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /sys/devices/system/cpu/{online,possible} r,
    /sys/fs/cgroup/cpu.max r,
    /proc/{self,thread-self}/{cgroup,mountinfo} r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm//{api,worker},
  }

  profile patcher flags=(complain,attach_disconnected,mediate_deleted) {
    # node /backend/utils/rom_patcher/patcher.js <rom> <patch> <output>.
    # Only the bundled patcher code; no npm, shell, or network.
    /usr/bin/node mr,
    /lib/ld-musl-aarch64.so.1 mr,
    /usr/lib/{libada.so.3.3.0,libbrotlicommon.so.1.2.0,libbrotlidec.so.1.2.0,libbrotlienc.so.1.2.0,libcares.so.2.19.7,libcrypto.so.3,libgcc_s.so.1} mr,
    /usr/lib/{libicudata.so.78.1,libicui18n.so.78.1,libicuuc.so.78.1,libnghttp2.so.14.29.5,libsimdjson.so.29.0.0,libsimdutf.so.34.0.0,libsqlite3.so.0,libssl.so.3,libstdc++.so.6.0.34,libz.so.1,libzstd.so.1} mr,
    /backend/utils/rom_patcher/ r,
    /backend/utils/rom_patcher/{patcher.js,package.json} r,
    /backend/utils/rom_patcher/rom-patcher-js/ r,
    /backend/utils/rom_patcher/rom-patcher-js/** r,
    /backend/ r,
    /backend/utils/ r,
    /romm/library/ r,
    /romm/library/** r,
    /tmp/ r,
    /tmp/tmp*/ rw,
    /tmp/tmp*/** rw,
    /etc/ssl/openssl.cnf r,
    /dev/null rw,
    /dev/urandom r,
    /proc/{self,thread-self}/{maps,status,stat} r,
    /proc/{self,thread-self}/fd/[0-9]* rw,
    /proc/{meminfo,cpuinfo} r,
    /sys/devices/system/cpu/{online,possible} r,
    /sys/fs/cgroup/{cpu.max,memory.max,memory.high} r,
    /proc/{self,thread-self}/{cgroup,mountinfo} r,
    signal (receive) peer=unconfined,
    signal (receive) peer=ghostship-romm//{api,worker},
    signal (send, receive) peer=ghostship-romm//patcher,
  }
}
