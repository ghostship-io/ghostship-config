{ config, lib, pkgs, ... }:

let
  bazarr-secrets = config.sops.secrets."bazarr-secrets".path;
  plex-secrets = config.sops.secrets."plex-secrets".path;
  sonarr-secrets = config.sops.secrets."sonarr-secrets".path;
  radarr-secrets = config.sops.secrets."radarr-secrets".path;
in
{
  virtualisation.oci-containers.containers."bazarr" = {
    image = "lscr.io/linuxserver/bazarr:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:6767/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      TZ = "UTC";
      PUID = "3000";
      PGID = "3000";
    };
    volumes = [
      "/srv/apps/bazarr:/config"
      "/mnt/share/Library/Movies:/movies"
      "/mnt/share/Library/TV:/tv"
    ];
  };

  systemd.services.podman-bazarr = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/bazarr 0755 apps apps -"
  ];

  system.activationScripts.bazarr-config = {
    text = ''
      CONFIG_DIR="/srv/apps/bazarr/config"
      CONFIG_FILE="$CONFIG_DIR/config.yaml"
      LEGACY_CONFIG_FILE="/srv/apps/bazarr/config.yaml"

      mkdir -p "$CONFIG_DIR"

      if [ ! -f "$CONFIG_FILE" ] && [ -f "$LEGACY_CONFIG_FILE" ]; then
        cp "$LEGACY_CONFIG_FILE" "$CONFIG_FILE"
      fi

      if [ -f "$CONFIG_FILE" ] && [ -f "${bazarr-secrets}" ] && [ -f "${plex-secrets}" ] && [ -f "${sonarr-secrets}" ] && [ -f "${radarr-secrets}" ]; then
        echo "Surgically updating Bazarr config..."
        set -a
        . "${bazarr-secrets}"
        . "${plex-secrets}"
        . "${sonarr-secrets}"
        . "${radarr-secrets}"
        set +a

        bazarr_args=(
          --secrets-file "${bazarr-secrets}"
          --secrets-file "${plex-secrets}"
          --secrets-file "${sonarr-secrets}"
          --secrets-file "${radarr-secrets}"
          auth.apikey=env:BAZARR_API_KEY
          general.flask_secret_key=env:BAZARR_FLASK_SECRET_KEY
          opensubtitlescom.password=env:BAZARR_OPENSUBTITLES_PASS
          plex.apikey=env:PLEX_API_KEY
          plex.encryption_key=env:BAZARR_PLEX_ENCRYPTION_KEY
          plex.token=env:BAZARR_PLEX_TOKEN
          radarr.apikey=env:RADARR_API_KEY
          sonarr.apikey=env:SONARR_API_KEY
          subdl.api_key=env:BAZARR_SUBDL_API_KEY
          general.instance_name=literal:"Ghostship Bazarr"
          analytics.enabled=literal:false
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${bazarr_args[@]}"

        chown 3000:3000 "$CONFIG_FILE"
        chmod 644 "$CONFIG_FILE"

        if [ -f "$LEGACY_CONFIG_FILE" ]; then
          rm -f "$LEGACY_CONFIG_FILE"
        fi
      fi
    '';
  };
}
