{ config, pkgs, ... }:
let
  python = pkgs.python3.withPackages (ps: [ ps.requests ]);
  provision = pkgs.writeShellScriptBin "ghostship-seerr-provision" ''
    set -euo pipefail
    export PATH=${pkgs.podman}/bin:$PATH
    set -a
    . ${config.ghostship.selfHostedSecrets.projections.plex.path}
    . ${config.ghostship.selfHostedSecrets.projections.sonarr.path}
    . ${config.ghostship.selfHostedSecrets.projections.radarr.path}
    set +a
    exec ${python}/bin/python ${./seerr-provision.py}
  '';
in
{
  environment.systemPackages = [ provision ];
  ghostship.apps.seerr = {
    healthPath = "/api/v1/status";
    name = "Seerr";
    group = "Media";
    description = "Media Requests";
    icon = "sh-seerr";
    order = 170;
    hostname = "requests.ghostship.io";
    origin = "http://seerr:5055";
    muximux = {
      icon = "fa-film";
    };
  };

  virtualisation.oci-containers.containers.seerr = {
    podman.sdnotify = "healthy";
    image = "ghcr.io/seerr-team/seerr:latest";
    pull = "always";
    labels."io.containers.autoupdate" = "registry";
    user = "3000:3000";
    environment = {
      TZ = "Pacific/Honolulu";
      LOG_LEVEL = "info";
    };
    volumes = [ "/srv/apps/seerr:/app/config:rw" ];
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q -O /dev/null --timeout=5 http://127.0.0.1:5055/api/v1/status"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
  };
  systemd.tmpfiles.rules = [ "d /srv/apps/seerr 0700 apps apps -" ];
  systemd.services.ghostship-seerr-provision = {
    description = "Initialize Seerr integrations without changing media profiles";
    requires = [
      "podman-seerr.service"
      "podman-plex.service"
      "podman-sonarr.service"
      "podman-radarr.service"
    ];
    after = [
      "podman-seerr.service"
      "podman-plex.service"
      "podman-sonarr.service"
      "podman-radarr.service"
    ];
    wantedBy = [ "multi-user.target" ];
    onFailure = [ "ghostship-failure@%n.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${provision}/bin/ghostship-seerr-provision";
      TimeoutStartSec = "5min";
      UMask = "0077";
    };
  };
}
