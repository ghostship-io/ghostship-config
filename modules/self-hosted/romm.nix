{ config, lib, pkgs, ... }:

let
  romm-secrets = config.sops.secrets."romm-secrets".path;
in
{
  virtualisation.oci-containers.containers."romm" = {
    image = "rommapp/romm:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:8080/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
    ];
    environment = {
      # Most environment is now managed via env file in preStart to ensure consistency with secrets
    };
    environmentFiles = [
      "/srv/apps/romm/romm.env"
    ];
    volumes = [
      "/srv/apps/romm/resources:/romm/resources:rw"
      "/srv/apps/romm/redis-data:/redis-data:rw"
      "/srv/apps/romm/config:/romm/config:rw"
      "/mnt/share/Library/ROMs:/romm/library:rw"
      "/mnt/share/Library/ROMs/.romm:/romm/assets:rw"
    ];
  };

  systemd.services.podman-romm = {
    after = [ "mnt-share.mount" ];
    wants = [ "mnt-share.mount" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/romm 0755 apps apps -"
    "d /srv/apps/romm/resources 0755 apps apps -"
    "d /srv/apps/romm/redis-data 0755 apps apps -"
    "d /srv/apps/romm/config 0755 apps apps -"
  ];

  systemd.services.podman-romm.preStart = ''
    CONFIG_DIR="/srv/apps/romm"
    CONFIG_FILE="$CONFIG_DIR/config/config.yml"
    ENV_FILE="$CONFIG_DIR/romm.env"

    if [ -f "$CONFIG_FILE" ]; then
      echo "Surgically updating RomM config.yml..."
      
      romm_cfg_args=(
        library_path=literal:/romm/library
        assets_path=literal:/romm/assets
        resources_path=literal:/romm/resources
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" "''${romm_cfg_args[@]}"
      chown 3000:3000 "$CONFIG_FILE"
    fi

    echo "Surgically updating RomM env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    romm_env_args=(
      --secrets-file "${romm-secrets}"
      DB_HOST=literal:romm-db
      DB_NAME=literal:romm
      DB_USER=env:ROMM_DB_USER
      DB_PASSWD=env:ROMM_DB_PASS
      ROMM_AUTH_SECRET_KEY=env:ROMM_AUTH_SECRET
      IGDB_CLIENT_ID=env:ROMM_IGDB_CLIENT_ID
      IGDB_CLIENT_SECRET=env:ROMM_IGDB_CLIENT_SECRET
      RETROACHIEVEMENTS_API_KEY=env:ROMM_RETROACHIEVEMENTS_API_KEY
      STEAMGRIDDB_API_KEY=env:ROMM_STEAMGRIDDB_API_KEY
      SCREENSCRAPER_USER=env:ROMM_SCREENSCRAPER_USER
      SCREENSCRAPER_PASSWORD=env:ROMM_SCREENSCRAPER_PASS
      HASHEOUS_API_ENABLED=literal:true
      HLTB_API_ENABLED=literal:true
      ALLOWED_HOSTS=literal:romm.ghostship.io,apps.ghostship.io,*
      TRUSTED_PROXIES=literal:*
      ENABLE_CSP=literal:false
      ROMM_HTTP_PROXY=literal:true
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${romm_env_args[@]}"

    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
