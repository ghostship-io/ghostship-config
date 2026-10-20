# Kernel-enforced limits on running new code inside containers. AppArmor stays
# in complain mode while learning, so it blocks nothing yet. These mounts block
# exec, setuid and device nodes in temporary storage now. Data volumes carry the
# same options in each service module (`rw,noexec,nosuid,nodev`).
{ config, lib, ... }:
let
  tmp = size: "rw,noexec,nosuid,nodev,mode=1777,size=${size}";
  # Containers excluded from a noexec /tmp, with the reason:
  # - plex: handled with its codec-directory split (codecs load from /config).
  # - grimmory: pdfium4j extracts and maps libpdfium.so from /tmp.
  # - agent-desktop: interactive workstation; see docs/agent-desktop.md.
  # - t3code: never recreated by this repository.
  # - romm: stages uploads (multi-GB ROMs) in /tmp, so it gets a disk-backed noexec bind.
  noexecTmp = [
    "bazarr"
    "chaptarr"
    "cloudflared"
    "flaresolverr"
    "gluetun"
    "grimmory-db"
    "homepage"
    "muximux"
    "ntfy"
    "nzbget"
    "plex-auto-languages"
    "prowlarr"
    "pyload"
    "qbittorrent"
    "radarr"
    "recyclarr"
    "romm-db"
    "seerr"
    "sonarr"
    "tautulli"
    "tdarr"
    "uptime-kuma"
  ];
  # In-house read-only containers already mount a noexec /tmp; Podman's
  # read-only tmpfs leaves /var/tmp executable.
  optional =
    lib.optionals config.ghostship.githubEngineering.enable [
      "ghostship-github-coordinator"
      "ghostship-hooks"
    ]
    ++ lib.optional config.ghostship.privateIntegrations.enable "ghostship-private-integrations";
  # Capabilities each container keeps; every other one is dropped, so a setuid
  # binary in the image cannot regain them. Lists come from each container's
  # strict AppArmor profile (apparmor/<container>.profile). Plex, the agent
  # desktop and T3 are out of scope here; the in-house images already drop ALL.
  keepCaps = {
    bazarr = rootLsio;
    chaptarr = [ ];
    cloudflared = [ ];
    flaresolverr = [ ];
    gluetun = [
      "CHOWN"
      "DAC_OVERRIDE"
      "NET_ADMIN"
      "NET_BIND_SERVICE"
    ];
    grimmory = [
      "CHOWN"
      "SETGID"
      "SETUID"
    ];
    grimmory-db = [ ];
    homepage = [ ];
    muximux = [
      "CHOWN"
      "DAC_OVERRIDE"
      "FOWNER"
      "KILL"
      "NET_BIND_SERVICE"
      "SETGID"
      "SETUID"
    ];
    ntfy = [ ];
    nzbget = rootLsio;
    plex-auto-languages = [ ];
    prowlarr = rootLsio;
    pyload = rootLsio;
    qbittorrent = rootLsio;
    radarr = rootLsio;
    recyclarr = [ ];
    romm = [ ];
    romm-db = rootLsio;
    seerr = [ ];
    sonarr = rootLsio;
    tautulli = rootLsio;
    tdarr = rootLsio ++ [ "FSETID" ];
    uptime-kuma = [ ];
  };
  # LinuxServer images: s6 preinit runs as root (directly, or through the
  # setuid-root s6-overlay-suexec when started as the app user), chowns, then
  # drops to the app user. Without these it fails "unable to setgid to root".
  rootLsio = [
    "CHOWN"
    "DAC_OVERRIDE"
    "FOWNER"
    "KILL"
    "SETGID"
    "SETUID"
  ];
in
{
  virtualisation.oci-containers.containers = lib.mkMerge [
    (lib.mapAttrs (_: caps: {
      extraOptions = [ "--cap-drop=ALL" ] ++ map (cap: "--cap-add=${cap}") caps;
    }) keepCaps)
    (lib.genAttrs noexecTmp (_: {
      extraOptions = [
        "--tmpfs=/tmp:${tmp "2g"}"
        "--tmpfs=/var/tmp:${tmp "512m"}"
      ];
    }))
    (lib.genAttrs optional (_: {
      extraOptions = [ "--tmpfs=/var/tmp:${tmp "64m"}" ];
    }))
    {
      grimmory.extraOptions = [ "--tmpfs=/var/tmp:${tmp "512m"}" ];
      romm = {
        volumes = [ "/srv/apps/romm/tmp:/tmp:rw,noexec,nosuid,nodev" ];
        extraOptions = [ "--tmpfs=/var/tmp:${tmp "512m"}" ];
      };
    }
  ];
  systemd.tmpfiles.rules = [ "d /srv/apps/romm/tmp 1777 root root - -" ];
}
