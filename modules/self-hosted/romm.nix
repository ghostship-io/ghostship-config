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
      "--health-cmd=/bin/sh -c 'for _ in $(seq 1 30); do wget -q --spider http://127.0.0.1:8080 && exit 0; sleep 2; done; exit 1'"
      "--health-interval=1m"
      "--health-timeout=75s"
      "--health-retries=3"
      "--health-start-period=30s"
    ];
    environment = {
      DB_HOST = "romm-db";
      DB_NAME = "romm";
      HASHEOUS_API_ENABLED = "true";
      HLTB_API_ENABLED = "true";
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
      ${pkgs.ghostship-config}/bin/ghostship-config set "$CONFIG_FILE" \
        library_path=literal:/romm/library \
        assets_path=literal:/romm/assets \
        resources_path=literal:/romm/resources
      chown 3000:3000 "$CONFIG_FILE"
    fi

    echo "Surgically updating RomM env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" \
      --secrets-file "${romm-secrets}" \
      DB_USER=env:ROMM_DB_USER \
      DB_PASSWD=env:ROMM_DB_PASSWORD \
      ROMM_AUTH_SECRET_KEY=env:ROMM_AUTH_SECRET \
      IGDB_CLIENT_ID=env:ROMM_IGDB_CLIENT_ID \
      IGDB_CLIENT_SECRET=env:ROMM_IGDB_CLIENT_SECRET \
      RETROACHIEVEMENTS_API_KEY=env:ROMM_RETROACHIEVEMENTS_API_KEY \
      STEAMGRIDDB_API_KEY=env:ROMM_STEAMGRIDDB_API_KEY \
      SCREENSCRAPER_USER=env:ROMM_SCREENSCRAPER_USER \
      SCREENSCRAPER_PASSWORD=env:ROMM_SCREENSCRAPER_PASS

    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
