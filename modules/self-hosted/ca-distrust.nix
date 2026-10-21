# Distrust CA roots behind compromised intermediates, on the host and in every
# third-party container, before the images ship patched trust stores.
#
# eMudhra (2026-10-20): the private keys of eight eMudhra intermediates leaked,
# so anyone holding them can issue a certificate for any name. They chain to
# emSign ECC Root CA - G3 (by cross-sign) and to Comodo AAA Services root.
# Browsers block the intermediates; Debian, Ubuntu and Alpine shipped fixes the
# images had not picked up. NixOS's bundle already limits the AAA root to email.
# Remove this once nixpkgs' cacert and every image distrust the chains; check
# with `curl https://dv-g3b-emudhra.we-have-a-problem.com/` (must fail).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  roots = [
    "emSign ECC Root CA - G3"
    "Comodo AAA Services root"
  ];
  # The host's trust bundle with the roots removed (security.pki).
  bundle = config.environment.etc."ssl/certs/ca-certificates.crt".source;
  blank = pkgs.writeText "distrusted-root.crt" "";
  path = "/etc/ssl/certs/ca-certificates.crt";
  # Third-party images. The bundle replaces the CAfile; blanking the roots'
  # files also removes them from OpenSSL's hashed CApath lookup (/etc/ssl/certs/
  # links into /usr/share/ca-certificates). Podman creates a missing target, so
  # an image without one of these files still starts. In-house images use the
  # host bundle directly. Excluded: t3code (never recreated by this repository)
  # and agent-desktop (Chrome blocks the chains itself; recreating interrupts
  # sessions).
  containers = [
    "bazarr"
    "chaptarr"
    "cloudflared"
    "flaresolverr"
    "gluetun"
    "grimmory"
    "grimmory-db"
    "homepage"
    "muximux"
    "ntfy"
    "nzbget"
    "plex"
    "plex-auto-languages"
    "prowlarr"
    "pyload"
    "qbittorrent"
    "radarr"
    "recyclarr"
    "romm"
    "romm-db"
    "seerr"
    "sonarr"
    "tautulli"
    "tdarr"
    "uptime-kuma"
  ];
  # Node.js uses its own compiled-in roots unless told to use OpenSSL's store.
  node = [
    "homepage"
    "seerr"
    "uptime-kuma"
  ];
in
{
  security.pki.caCertificateBlacklist = roots;

  virtualisation.oci-containers.containers = lib.mkMerge [
    (lib.genAttrs containers (_: {
      volumes = [
        "${bundle}:${path}:ro"
        "${blank}:/usr/share/ca-certificates/mozilla/emSign_ECC_Root_CA_-_G3.crt:ro"
        "${blank}:/usr/share/ca-certificates/mozilla/Comodo_AAA_Services_root.crt:ro"
      ];
      environment = {
        SSL_CERT_FILE = path;
        # Python requests reads certifi's own bundle otherwise.
        REQUESTS_CA_BUNDLE = path;
      };
    }))
    (lib.genAttrs node (_: {
      environment.NODE_OPTIONS = "--use-openssl-ca";
    }))
    # Plex verifies with its own bundled roots, which include both.
    { plex.volumes = [ "${bundle}:/usr/lib/plexmediaserver/Resources/cacert.pem:ro" ]; }
  ];
}
