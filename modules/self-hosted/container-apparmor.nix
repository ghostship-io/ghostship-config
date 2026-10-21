# Strict per-container AppArmor policies. Each container's policy lives in
# apparmor/<container>.profile as `profile ghostship-<container>`; its child
# profiles (named here relative to it) are the process labels the review expects.
# Plex, ntfy, hooks and agent-desktop declare their policies in their own modules.
{ config, lib, ... }:
let
  strict = {
    # app name = { container (default: app name); children; required (default:
    # children); top = false when no long-running process keeps the top label }
    sonarr = {
      children = [ "server" "readiness" "tools" "ffprobe" ];
      required = [ "server" ];
    };
    radarr = {
      children = [ "server" "readiness" "tools" "ffprobe" ];
      required = [ "server" ];
    };
    prowlarr = {
      children = [ "server" "readiness" "tools" ];
      required = [ "server" ];
    };
    bazarr = {
      children = [ "python" "readiness" "tools" "ffprobe" "unrar" ];
      required = [ "python" ];
    };
    # The image has no cat; cloudflared reads the boot ID as a (rejected) config.
    cloudflared.heartbeat = [
      "@entrypoint"
      "--config"
      "/proc/sys/kernel/random/boot_id"
      "tunnel"
      "ingress"
      "validate"
    ];
    homepage = {
      children = [ "server" "tools" "sysinfo" ];
      required = [ "server" ];
      top = false;
    };
    uptime-kuma = {
      children = [ "server" ];
    };
    seerr = {
      children = [ "npm" "server" "launch" "tools" ];
      required = [ "npm" "server" ];
      top = false;
    };
    muximux = {
      children = [ "nginx" "php" "phpexec" "patcher" "git" "logrotate" ];
      required = [ "nginx" "php" ];
    };
    romm = {
      children = [ "api" "worker" "valkey" "nginx" "tools" "templates" "startup" "archive" "rahasher" "converto" "patcher" ];
      required = [ "api" "worker" "valkey" "nginx" ];
    };
    romm-db = {
      children = [ "safe" "server" "client" "upgrade" ];
      required = [ "safe" "server" ];
    };
    grimmory-db = {
      children = [ "server" "client" ];
      required = [ "server" ];
      top = false;
    };
    grimmory = {
      children = [ "server" "ffprobe" "kepubify" ];
      required = [ "server" ];
      top = false;
    };
    recyclarr = {
      children = [ "cron" "job" "recyclarr" "git" ];
      required = [ "cron" ];
      top = false;
    };
    plex-auto-languages = {
      children = [ "python" "healthcheck" ];
      required = [ "python" ];
      top = false;
    };
    tautulli = {
      children = [ "tautulli" "readiness" "tools" ];
      required = [ "tautulli" ];
    };
    nzbget = {
      children = [ "server" "extract" "readiness" "tools" "sysinfo" ];
      required = [ "server" ];
    };
    pyload = {
      children = [ "pyload" "tools" "ffmpeg" "readiness" ];
      required = [ "pyload" "tools" ];
    };
    qbittorrent = {
      children = [ "server" "tools" "readiness" ];
      required = [ "server" "tools" ];
    };
    gluetun = {
      children = [ "firewall" "portforward" "healthcheck" "openvpn" ];
      required = [ ];
    };
    flaresolverr = {
      children = [ "python" "chromedriver" "chromium" "xvfb" "healthcheck" "tools" ];
      required = [ "python" ];
    };
    tdarr = {
      children = [ "server" "node" "worker" "transcode" "exiftool" "scanner" "healthcheck" ];
      required = [ "server" "node" ];
    };
    # no_new_privs containers: AppArmor never enters child profiles, so flat.
    github-coordinator = {
      container = "ghostship-github-coordinator";
      # No cat or shell in the image; its Python reads the boot ID.
      heartbeat = [
        "@entrypoint"
        "-c"
        "open('/proc/sys/kernel/random/boot_id').read()"
      ];
    };
    ghostship.container = "ghostship-private-integrations";
    chaptarr = {
      children = [ "server" "healthcheck" ];
      required = [ "server" ];
      top = false;
    };
    # SIEM stores (siem/storage.nix). The images have no shell or cat: the
    # binary reads the boot ID as a TLS certificate, fails and exits.
    victorialogs.heartbeat = victoriaHeartbeat 19428;
    victoriametrics.heartbeat = victoriaHeartbeat 18428;
    # SIEM UI (siem/ui.nix): distroless Grafana cannot safely read the boot ID
    # itself (any config starts a server), so a static read-only helper does.
    grafana.heartbeat = [ "/opt/ghostship-heartbeat/read-file" "/proc/sys/kernel/random/boot_id" ];
    vmauth.heartbeat = [
      "@entrypoint"
      "-auth.config=/proc/sys/kernel/random/boot_id"
      "-httpListenAddr=127.0.0.1:18427"
    ];
    # Both vmalert instances share apparmor/vmalert.profile (siem/alerting.nix).
    vmalert-logs = {
      source = "vmalert";
      heartbeat = vmalertHeartbeat 18880;
    };
    vmalert-metrics = {
      source = "vmalert";
      heartbeat = vmalertHeartbeat 18881;
    };
  };
  # vmalert has no store but refuses to start without rules and a datasource.
  vmalertHeartbeat = port: [
    "@entrypoint"
    "-tls"
    "-tlsCertFile=/proc/sys/kernel/random/boot_id"
    "-tlsKeyFile=/proc/sys/kernel/random/boot_id"
    "-rule=/rules/metrics.yml"
    "-datasource.url=http://127.0.0.1:1"
    "-notifier.blackhole"
    "-httpListenAddr=127.0.0.1:${toString port}"
  ];
  victoriaHeartbeat = port: [
    "@entrypoint"
    "-tls"
    "-tlsCertFile=/proc/sys/kernel/random/boot_id"
    "-tlsKeyFile=/proc/sys/kernel/random/boot_id"
    "-storageDataPath=/tmp/heartbeat"
    "-httpListenAddr=127.0.0.1:${toString port}"
  ];
  enabled =
    name:
    if name == "github-coordinator" then
      config.ghostship.githubEngineering.enable
    else if name == "ghostship" then
      config.ghostship.privateIntegrations.enable
    else
      true;
  entries = lib.mapAttrsToList (
    name: spec:
    rec {
      inherit name;
      container = spec.container or name;
      profile = if lib.hasPrefix "ghostship-" container then container else "ghostship-${container}";
      children = spec.children or [ ];
      required = spec.required or children;
      top = spec.top or true;
      heartbeat = spec.heartbeat or null;
      source = spec.source or container;
    }
  ) strict;
in
{
  ghostship.apps = builtins.listToAttrs (
    map (
      e:
      lib.nameValuePair e.name (
        lib.mkIf (enabled e.name) {
          apparmorProfile = e.profile;
          apparmorHeartbeat = e.heartbeat;
          apparmorProcessProfiles = [ e.profile ] ++ map (c: "${e.profile}//${c}") e.children;
          apparmorRequiredProcessProfiles =
            lib.optional e.top e.profile ++ map (c: "${e.profile}//${c}") e.required;
        }
      )
    ) entries
  );

  security.apparmor.policies = builtins.listToAttrs (
    map (
      e:
      lib.nameValuePair e.profile (
        lib.mkIf (enabled e.name) {
          state = "complain";
          # A shared source names its profile ghostship-<source>; rename it per container.
          profile = builtins.replaceStrings [ "complain," "ghostship-${e.source}" ] [ "" e.profile ] (
            builtins.readFile (./apparmor + "/${e.source}.profile")
          );
        }
      )
    ) entries
  );
}
