{ config, pkgs, ... }:

let
  hermes-startup = pkgs.writeText "hermes-startup.sh" ''
    set -eu

    mkdir -p /tmp
    chmod 1777 /tmp

    mkdir -p /home/hermes/.honcho
    if [ -n "''${HONCHO_API_KEY:-}" ] && [ -n "''${HONCHO_BASE_URL:-}" ]; then
      cat > /home/hermes/.honcho/config.json <<EOF
{
  "apiKey": "$HONCHO_API_KEY",
  "baseUrl": "$HONCHO_BASE_URL",
  "hosts": {
    "hermes": {
      "workspace": "hermes",
      "peerName": "hermes",
      "aiPeer": "hermes",
      "memoryMode": "hybrid",
      "enabled": true
    }
  }
}
EOF
      chown -R 3000:3000 /home/hermes/.honcho
    fi

    exec /nix/store/4avjjjj02q5m84w4q1k7lrf5g8mkwkmb-ghostship-hermes-runtime/bin/ghostship-hermes-runtime entrypoint
  '';
  hermes-secrets = config.sops.secrets."hermes-secrets".path;
  romm-secrets = config.sops.secrets."romm-secrets".path;
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
  prowlarr-secrets = config.sops.secrets."prowlarr-secrets".path;
  plex-secrets = config.sops.secrets."plex-secrets".path;
  tautulli-secrets = config.sops.secrets."tautulli-secrets".path;
  bazarr-secrets = config.sops.secrets."bazarr-secrets".path;
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
in
{
  virtualisation.oci-containers.containers."hermes" = {
    image = "ghcr.io/ghostship-io/ghostship-hermes:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:7681/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      TTYD_PORT = "7681";
      TTYD_TITLE = "Ghostship Hermes";
      TTYD_SESSION_NAME = "hermes";
      SEARXNG_URL = "http://gluetun:5002";
      SONARR_URL = "http://sonarr:8989";
      RADARR_URL = "http://radarr:7878";
      PROWLARR_URL = "http://prowlarr:9696";
      PLEX_URL = "http://plex:32400";
      ROMM_URL = "http://romm:8080";
      NZBGET_URL = "http://gluetun:5001";
      QBITTORRENT_URL = "http://gluetun:5000";
      GRIMMORY_URL = "http://grimmory:6060";
      TAUTULLI_URL = "http://tautulli:8181";
      BAZARR_URL = "http://bazarr:6767";
      FLARESOLVERR_URL = "http://flaresolverr:8191";
      PYLOAD_URL = "http://pyload:8000";
      CLOAKBROWSER_URL = "http://cloakbrowser:8080";
      HONCHO_API_KEY = "honcho";
      HONCHO_BASE_URL = "http://honcho:8000";
      SYNOLOGY_VERIFY_SSL = "false";
    };
    entrypoint = "/bin/sh";
    cmd = [ "/hermes-startup.sh" ];
    environmentFiles = [
      hermes-secrets
      romm-secrets
      sonarr-secrets
      radarr-secrets
      prowlarr-secrets
      plex-secrets
      tautulli-secrets
      bazarr-secrets
      grimmory-secrets
    ];
    volumes = [
      "/srv/apps/hermes/home:/home/hermes/.hermes:rw"
      "/srv/apps/hermes/home/.honcho:/home/hermes/.honcho:rw"
      "hermes-nix:/nix:rw"
      "${hermes-startup}:/hermes-startup.sh:ro"
    ];
  };

  systemd.services.podman-hermes.preStart = ''
    if [ ! -f "${hermes-secrets}" ]; then
      echo "Waiting for Hermes secrets at ${hermes-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${hermes-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${hermes-secrets}" ]; then
      echo "Missing Hermes secrets file at ${hermes-secrets}" >&2
      exit 1
    fi
  '';

  systemd.tmpfiles.rules = [
    "d /srv/apps/hermes 0755 apps apps -"
    "d /srv/apps/hermes/home 0755 apps apps -"
    "d /srv/apps/hermes/home/.honcho 0755 apps apps -"
  ];
}
