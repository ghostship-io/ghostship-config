# Container policy, inspected on chill-penguin (aarch64), 2026-10-20:
# localhost/ghostship-private-integrations:6dd3aiff387mg9sb8g96jfy6vk8w73dv, the
# ghostship-private-agent Nix image (private-integrations.nix). uid/gid 62020;
# --cap-drop=ALL, no-new-privileges, read-only root, /tmp tmpfs noexec.
# Process tree: ghostship-integration-supervisor (bash) -> python3 supervisor.py
#   -> python3 -m ghostship_mcp.server (backend on /tmp/ghostship-mcp/*.sock)
#   -> tunnel-client (OpenAI relay) -> ghostship-mcp (sh) -> env -> python3
#      -m ghostship_mcp.stdio_proxy, one per relay session.
# The backend runs the Printing Press clients, ssh to the Agent Desktop, and
# pdftoppm/tesseract for health-document OCR.
# Flat profile: under no_new_privs AppArmor never enters a cx child, so every
# allowed executable is `ix` here. /bin/* coreutils is one multicall binary.
# No explicit deny: those rules would enforce even while in complain mode.
# No abstractions: their implicit permissions would obscure this allowlist.
# Only store hashes are globbed: an image rebuild that changes a package
# version requires review.
profile ghostship-private-integrations flags=(complain,attach_disconnected,mediate_deleted) {
  network inet stream,
  network inet6 stream,
  network inet dgram,
  network inet6 dgram,
  # The backend socket in /tmp and the host brokers' sockets under /run.
  unix (create, bind, listen, accept, connect, send, receive, getattr, getopt, setopt, shutdown) type=stream,

  signal (receive) peer=unconfined,
  signal (send, receive) peer=ghostship-private-integrations,

  # ---- Executables ----
  /nix/store/*-bash-5.3p3/bin/bash rix,
  /nix/store/*-bash-interactive-5.3p3/bin/bash rix,
  /nix/store/*-coreutils-9.8/bin/coreutils rix,
  /nix/store/*-python3-3.13.12/bin/python3.13 rix,
  /nix/store/*-openai-tunnel-client-runtime-0.0.15/bin/tunnel-client rix,
  /nix/store/*-openssh-10.3p1/bin/ssh rix,
  /nix/store/*-poppler-utils-25.10.0/bin/pdftoppm rix,
  /nix/store/*-tesseract-5.5.1/bin/tesseract rix,
  /nix/store/*-{bazarr,chaptarr,costco,gluetun,grimmory,nzbget,plex,prowlarr,pyload,qbittorrent,radarr,romm,seerr,sonarr,tautulli,tdarr,ultrahuman}-pp-cli-0.0.0/bin/{bazarr,chaptarr,costco,gluetun,grimmory,nzbget,plex,prowlarr,pyload,qbittorrent,radarr,romm,seerr,sonarr,tautulli,tdarr,ultrahuman}-pp-cli rix,
  # Script entrypoints: the container entrypoint (bash) and the relay's
  # ghostship-mcp launcher (sh); exec of a script is mediated on the script.
  /nix/store/*-ghostship-integration-supervisor/bin/ghostship-integration-supervisor rix,
  /nix/store/*-ghostship-private-mcp-runtime/bin/ghostship-mcp rix,
  /nix/store/*-supervisor.py r,
  /nix/store/*-ghostship-private-mcp-runtime/{,**} r,

  # ---- Libraries ----
  /nix/store/*-acl-2.3.2/lib/libacl.so.1.1.2302 mr,
  /nix/store/*-attr-2.5.2/lib/libattr.so.1.1.2502 mr,
  /nix/store/*-brotli-1.1.0-lib/lib/{libbrotlicommon.so.1.1.0,libbrotlidec.so.1.1.0} mr,
  /nix/store/*-bzip2-1.0.8/lib/libbz2.so.1.0.8 mr,
  /nix/store/*-curl-8.19.0/lib/libcurl.so.4.8.0 mr,
  /nix/store/*-expat-2.7.5/lib/libexpat.so.1.11.3 mr,
  /nix/store/*-fontconfig-2.17.1-lib/lib/libfontconfig.so.1.16.1 mr,
  /nix/store/*-freetype-2.13.3/lib/libfreetype.so.6.20.2 mr,
  /nix/store/*-gcc-14.3.0-lib/lib/{libgomp.so.1.0.0,libstdc++.so.6.0.33} mr,
  /nix/store/*-gcc-14.3.0-libgcc/lib/libgcc_s.so.1 mr,
  /nix/store/*-gdbm-1.26-lib/lib/{libgdbm.so.6.0.0,libgdbm_compat.so.4.0.0} mr,
  /nix/store/*-giflib-5.2.2/lib/libgif.so.7.2.0 mr,
  /nix/store/*-glibc-2.40-224/lib/{ld-linux-aarch64.so.1,libc.so.6,libdl.so.2,libm.so.6,libnss_dns.so.2,libnss_files.so.2,libpthread.so.0,libresolv.so.2,librt.so.1} mr,
  /nix/store/*-glibc-2.40-224/lib/locale/C.utf8/{,**} r,
  /nix/store/*-gmp-with-cxx-6.3.0/lib/libgmp.so.10.5.0 mr,
  /nix/store/*-keyutils-1.6.3-lib/lib/libkeyutils.so.1.10 mr,
  /nix/store/*-krb5-1.22.1-lib/lib/{libcom_err.so.3.0,libgssapi_krb5.so.2.2,libk5crypto.so.3.1,libkrb5.so.3.3,libkrb5support.so.0.1} mr,
  /nix/store/*-lcms2-2.17/lib/liblcms2.so.2.0.17 mr,
  /nix/store/*-ldns-1.8.4/lib/libldns.so.3.6.0 mr,
  /nix/store/*-leptonica-1.85.0/lib/libleptonica.so.6.0.0 mr,
  /nix/store/*-lerc-4.0.0/lib/libLerc.so.4 mr,
  /nix/store/*-libarchive-3.8.7-lib/lib/libarchive.so.13.8.7 mr,
  /nix/store/*-libdeflate-1.25/lib/libdeflate.so.0 mr,
  /nix/store/*-libffi-3.5.2/lib/libffi.so.8.2.0 mr,
  /nix/store/*-libidn2-2.3.8/lib/libidn2.so.0.4.0 mr,
  /nix/store/*-libjpeg-turbo-3.1.4/lib/libjpeg.so.62.4.0 mr,
  /nix/store/*-libpng-apng-1.6.56/lib/libpng16.so.16.56.0 mr,
  /nix/store/*-libpsl-0.21.5/lib/libpsl.so.5.3.5 mr,
  /nix/store/*-libssh2-1.11.1/lib/libssh2.so.1.0.1 mr,
  /nix/store/*-libtiff-4.7.1/lib/libtiff.so.6.2.0 mr,
  /nix/store/*-libunistring-1.4.1/lib/libunistring.so.5.2.1 mr,
  /nix/store/*-libwebp-1.6.0/lib/{libsharpyuv.so.0.1.2,libwebp.so.7.2.0,libwebpmux.so.3.1.2} mr,
  /nix/store/*-libxml2-2.15.1/lib/libxml2.so.16.1.1 mr,
  /nix/store/*-mpdecimal-4.0.1/lib/libmpdec.so.4.0.1 mr,
  /nix/store/*-ncurses-6.5/lib/{libncursesw.so.6.5,libpanelw.so.6.5} mr,
  /nix/store/*-nghttp2-1.68.1-lib/lib/libnghttp2.so.14.29.3 mr,
  /nix/store/*-nghttp3-1.15.0/lib/libnghttp3.so.9.6.1 mr,
  /nix/store/*-ngtcp2-1.22.1/lib/{libngtcp2.so.16.8.1,libngtcp2_crypto_ossl.so.0.2.0} mr,
  /nix/store/*-nspr-4.38.2/lib/{libnspr4.so,libplc4.so,libplds4.so} mr,
  /nix/store/*-nss-3.112.5/lib/{libnss3.so,libnssutil3.so,libsmime3.so} mr,
  /nix/store/*-openjpeg-2.5.4/lib/libopenjp2.so.2.5.4 mr,
  /nix/store/*-openssl-3.6.2/lib/{libcrypto.so.3,libssl.so.3} mr,
  /nix/store/*-poppler-utils-25.10.0/lib/libpoppler.so.154.0.0 mr,
  /nix/store/*-python3-3.13.12/lib/libpython3.13.so.1.0 mr,
  /nix/store/*-readline-8.3p1/lib/{libhistory.so.8.3,libreadline.so.8.3} mr,
  /nix/store/*-sqlite-3.50.4/lib/libsqlite3.so.3.50.4 mr,
  /nix/store/*-tesseract-5.5.1/lib/libtesseract.so.5.0.5 mr,
  /nix/store/*-util-linux-minimal-2.41.4-lib/lib/libuuid.so.1.3.0 mr,
  /nix/store/*-xz-5.8.3/lib/liblzma.so.5.8.3 mr,
  /nix/store/*-zlib-1.3.2/lib/libz.so.1.3.2 mr,
  /nix/store/*-zstd-1.5.7/lib/libzstd.so.1.5.7 mr,

  # ---- Python ----
  /nix/store/*-python3-3.13.12-env/{,**} r,
  /nix/store/*-python3-3.13.12/lib/python3.13/{,**} r,
  /nix/store/*-python3-3.13.12/lib/python3.13/lib-dynload/*.cpython-313-aarch64-linux-gnu.so mr,
  /nix/store/*-python3.13-*/lib/python3.13/site-packages/{,**} r,
  /nix/store/*-python3.13-{charset-normalizer-3.4.3,pydantic-core-2.33.2,rpds-py-0.25.0,websockets-15.0.1}/lib/python3.13/site-packages/*/*.cpython-313-aarch64-linux-gnu.so mr,
  /nix/store/*-python3.13-pycryptodomex-3.23.0/lib/python3.13/site-packages/Cryptodome/*/*.abi3.so mr,

  # ---- Data files ----
  /nix/store/*-nss-cacert-3.123/etc/ssl/certs/ca-bundle.crt r,
  /nix/store/*-openssl-3.6.2/etc/ssl/openssl.cnf r,
  /nix/store/*-tzdata-2026a/share/zoneinfo/{,**} r,
  /nix/store/*-mailcap-2.1.54/etc/mime.types r,
  /nix/store/*-iana-etc-20250505/etc/{services,protocols} r,
  /nix/store/*-openssh-10.3p1/etc/ssh/{,**} r,
  /nix/store/*-tesseract-5.5.1/share/tessdata/{,**} r,
  /nix/store/*-poppler-data-0.4.12/share/poppler/{,**} r,
  /nix/store/*-fontconfig-2.17.1/etc/fonts/{,**} r,
  /nix/store/*-dejavu-fonts-minimal-2.37/share/fonts/{,**} r,

  /etc/{passwd,group,hosts,hostname,resolv.conf,nsswitch.conf,localtime,mtab} r,
  /etc/ssh/{,**} r,
  /etc/ssl/{,**} r,
  /dev/null rw,
  /dev/{random,urandom} r,
  /dev/tty rw,
  /proc/{self,thread-self}/{fd/,stat,status,maps,mountinfo,cgroup,cmdline} r,
  /proc/[0-9]*/{stat,cmdline} r,
  /proc/{stat,meminfo,cpuinfo,mounts} r,
  /sys/kernel/mm/transparent_hugepage/hpage_pmd_size r,
  /sys/fs/cgroup/{,cpu.max,memory.max} r,

  # ---- Credentials and broker sockets (read-only mounts) ----
  /run/ghostship-integrations/{,**} r,
  /run/ghostship-integrations/inference-socket/* rw,
  /run/ghostship-keep/ r,
  /run/ghostship-keep/operations.sock rw,
  /run/ghostship-hostops/ r,
  /run/ghostship-hostops/ops.sock rw,
  /run/ghostship-secrets/{,**} r,

  # ---- Writable state ----
  # /state is HOME and XDG_STATE_HOME/<profile> (durable jobs).
  /state/ r,
  owner /state/ghostship/ rw,
  owner /state/ghostship/** rwk,
  /tmp/ r,
  owner /tmp/** rwk,
  /var/tmp/ r,

  # Healthcheck: `test -f /tmp/supervisor-live` with date/stat (coreutils).
  # The AppArmor review's heartbeat `podman exec ... /bin/cat` (coreutils).
  audit /proc/sys/kernel/random/boot_id r,
}
