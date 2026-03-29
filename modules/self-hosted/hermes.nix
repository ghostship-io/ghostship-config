{ config, lib, pkgs, ... }:

let
  plex-secrets = config.sops.secrets."plex-secrets".path;
in
{
  virtualisation.oci-containers.containers."hermes" = {
    image = "ghcr.io/ghostship-io/ghostship-hermes:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:7681/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=5m"
      "--health-on-failure=kill"
    ];
    environment = {
      HERMES_URL = "http://hermes:7681";
    };
    environmentFiles = [
      "/srv/apps/hermes/hermes.env"
    ];
    volumes = [
      "/srv/apps/hermes/home:/home/hermes/.hermes:rw"
      "/srv/apps/hermes/nix:/nix:rw"
    ];
  };

  systemd.services.podman-hermes = {
    after = [ "podman-gluetun.service" ];
    wants = [ "podman-gluetun.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/hermes 0755 apps apps -"
    "d /srv/apps/hermes/home 0755 apps apps -"
    "d /srv/apps/hermes/nix 0755 apps apps -"
  ];

  systemd.services.podman-hermes.preStart = ''
    ENV_FILE="/srv/apps/hermes/hermes.env"

    echo "Surgically updating Hermes env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    hermes_env_args=(
      --secrets-file "${plex-secrets}"

      SEARXNG_URL=literal:http://searxng:8080

      SONARR_URL=literal:http://sonarr:8989
      SONARR_API_KEY=env:SONARR_API_KEY

      RADARR_URL=literal:http://radarr:7878
      RADARR_API_KEY=env:RADARR_API_KEY

      PROWLARR_URL=literal:http://prowlarr:9696
      PROWLARR_API_KEY=env:PROWLARR_API_KEY

      PLEX_URL=literal:http://plex:32400
      PLEX_TOKEN=env:PLEX_TOKEN

      TAUTULLI_URL=literal:http://tautulli:8181
      TAUTULLI_API_KEY=env:TAUTULLI_API_KEY

      ROMM_URL=literal:http://romm:8080
      ROMM_TOKEN=env:ROMM_AUTH_SECRET

      GRIMMORY_URL=literal:http://grimmory:8050
      GRIMMORY_TOKEN=env:ROMM_AUTH_SECRET

      BAZARR_URL=literal:http://bazarr:6767
      BAZARR_API_KEY=env:BAZARR_API_KEY

      SYNOLOGY_URL=literal:http://192.168.200.106:5000
      SYNOLOGY_USER=env:SMB_USER
      SYNOLOGY_PASS=env:SMB_PASS

      FLARESOLVERR_URL=literal:http://flaresolverr:8191
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${hermes_env_args[@]}"

    chown 1000:1000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
