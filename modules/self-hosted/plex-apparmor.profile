# Container policy, inspected on chill-penguin (aarch64), 2026-10-18:
# LinuxServer Plex 1.43.4.10903; s6-overlay 3.2.1.0; uid/gid 3000.
# Load by name through the container runtime; there is no host attachment glob.
# The Internet-facing server and interpreter domains enforce (2026-10-21, user
# decision after Plex2Shell exploitation; Plex was already patched). Startup and
# the healthcheck keep learning in complain mode until their own review gate.
# The policy loads in enforce state, so each profile's flags decide its mode.
# Explicit deny rules always enforce; use them only for deliberate denials.
# No abstractions: their implicit permissions would obscure this allowlist.

@{ghostship_plex_pms} = /usr/lib/plexmediaserver
@{ghostship_plex_state} = "/config/Library/Application Support/Plex Media Server"
@{ghostship_plex_s6} = /package/admin/s6-overlay-3.2.1.0
@{ghostship_plex_plugins} = /usr/lib/plexmediaserver/Resources/Plug-ins-[0-9a-f]*
@{ghostship_plex_agents} = com.plexapp.system org.musicbrainz.agents.music com.plexapp.agents.{fanarttv,htbackdrops,imdb,lastfm,localmedia,lyricfind,movieposterdb,none,plexthememusic,themoviedb,thetvdb}

profile ghostship-plex flags=(complain,attach_disconnected,mediate_deleted) {
  # Startup stays in complain mode while collecting missing accesses. Omitted
  # permissions are NOT enforced in this domain.
  #include <plex-apparmor-startup.inc>
  "@{ghostship_plex_pms}/Plex Media Server" cx -> server,
  "@{ghostship_plex_pms}/Plex Script Host" px -> ghostship-plex//python,
  # Podman's healthcheck (reliability.nix) runs `sh -c "curl ... /identity"`.
  /usr/bin/curl cx -> healthcheck,

  profile server flags=(attach_disconnected,mediate_deleted) {
    # The server and its helpers get no shell, downloader, or startup-tool execs.
    "@{ghostship_plex_pms}/Plex Media Server" rix,
    # The "PMS GTP" thread reads its own processes' /proc entries; no tracing.
    ptrace (read, readby) peer=ghostship-plex//server,
    #include <plex-apparmor-runtime.inc>
  }

  # Inspected 2026-10-20 from the healthcheck's complain-mode records: curl
  # loads its libraries and resolver/TLS configuration, then probes localhost.
  profile healthcheck flags=(complain,attach_disconnected,mediate_deleted) {
    /usr/bin/curl rm,
    /usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1 rm,
    /usr/lib/aarch64-linux-gnu/lib{c.so.6,resolv.so.2,curl.so.4.8.0,z.so.1.3.1,zstd.so.1.5.7,brotlicommon.so.1.2.0,brotlidec.so.1.2.0,nghttp2.so.14.29.2,idn2.so.0.4.0,unistring.so.5.2.0,psl.so.5.3.4,rtmp.so.1,ssh2.so.1.0.1,ssl.so.3,crypto.so.3} rm,
    /usr/lib/aarch64-linux-gnu/lib{gnutls.so.30.41.1,nettle.so.8.11,hogweed.so.6.11,gmp.so.10.5.0,tasn1.so.6.6.5,p11-kit.so.0.4.8,ffi.so.8.2.0} rm,
    /usr/lib/aarch64-linux-gnu/lib{gssapi_krb5.so.2.2,krb5.so.3.3,k5crypto.so.3.1,krb5support.so.0.1,com_err.so.2.1,keyutils.so.1.10,ldap.so.2.0.200,lber.so.2.0.200,sasl2.so.2.0.25} rm,
    /etc/{ld.so.cache,nsswitch.conf,passwd,gnutls/config,ssl/openssl.cnf} r,
    /usr/lib/locale/locale-archive r,
    / r,
    /dev/null rw,
    network inet stream,
    network inet6 stream,
  }

  profile python flags=(attach_disconnected,mediate_deleted) {
    #include <plex-apparmor-python.inc>
  }

  # ctypes' `ldconfig -p` from the interpreter: read the loader cache, print.
  profile ldconfig flags=(attach_disconnected,mediate_deleted) {
    /usr/sbin/ldconfig rm,
    /etc/ld.so.cache r,
    /dev/null w,
  }
}
