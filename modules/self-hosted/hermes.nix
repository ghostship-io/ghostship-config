{ config, pkgs, ... }:

let
  hermes-secrets = config.sops.secrets."hermes-secrets".path;
  romm-secrets = config.sops.secrets."romm-secrets".path;
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
  prowlarr-secrets = config.sops.secrets."prowlarr-secrets".path;
  plex-secrets = config.sops.secrets."plex-secrets".path;
  tautulli-secrets = config.sops.secrets."tautulli-secrets".path;
  bazarr-secrets = config.sops.secrets."bazarr-secrets".path;
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
  hermes-home = "/srv/apps/hermes/home";
  hermes-workspace = "/srv/apps/hermes/workspace";
  hermes-nix = "/srv/apps/hermes/nix";
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
      HOME = "/home/hermes";
      HERMES_HOME = "/home/hermes/.hermes";
      TERMINAL_CWD = "/workspace";
      GHOSTSHIP_TERMINAL_CWD = "/workspace";
      GHOSTSHIP_WORKSPACE_ROOT = "/workspace";
      TTYD_PORT = "7681";
      TTYD_TITLE = "Ghostship Hermes";
      TTYD_SESSION_NAME = "hermes";
      SEARXNG_URL = "http://searxng:8080";
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
      N8N_URL = "http://n8n:5678";
      N8N_PUBLIC_URL = "https://n8n.ghostship.io";
      SYNOLOGY_VERIFY_SSL = "false";
    };
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
      "${hermes-home}:/home/hermes:rw"
      "${hermes-workspace}:/workspace:rw"
      "${hermes-nix}:/nix:rw"
    ];
  };

  systemd.services.podman-hermes.preStart = ''
    install -d -m0755 -o apps -g apps "${hermes-home}" "${hermes-workspace}"
    install -d -m0755 "${hermes-nix}"

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

    if [ ! -d "${hermes-nix}/store" ] || ! find "${hermes-nix}/store" -mindepth 1 -maxdepth 1 | read -r _; then
      echo "Seeding Hermes /nix from ghcr.io/ghostship-io/ghostship-hermes:latest"
      seed_container=""

      cleanup() {
        if [ -n "$seed_container" ]; then
          ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null 2>&1 || true
        fi
      }

      trap cleanup EXIT
      ${pkgs.podman}/bin/podman pull ghcr.io/ghostship-io/ghostship-hermes:latest >/dev/null
      seed_container="$(${pkgs.podman}/bin/podman create ghcr.io/ghostship-io/ghostship-hermes:latest)"
      find "${hermes-nix}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
      ${pkgs.podman}/bin/podman cp "$seed_container:/nix/." "${hermes-nix}/"
      cleanup
      trap - EXIT
    fi
  '';

  systemd.tmpfiles.rules = [
    "d /srv/apps/hermes 0755 apps apps -"
    "d /srv/apps/hermes/home 0755 apps apps -"
    "d /srv/apps/hermes/workspace 0755 apps apps -"
    "d /srv/apps/hermes/nix 0755 root root -"
  ];
}
