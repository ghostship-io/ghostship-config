{ config, lib, pkgs, ... }:

let
  romm-secrets = config.sops.secrets."romm-secrets".path;
in
{
  virtualisation.oci-containers.containers."romm-db" = {
    image = "lscr.io/linuxserver/mariadb:latest";
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=mariadb-admin ping -h 127.0.0.1 || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
      MYSQL_ROOT_HOST = "127.0.0.1";
      MYSQL_ALLOW_EMPTY_PASSWORD = "yes";
      MYSQL_DATABASE = "romm";
    };
    environmentFiles = [
      "/srv/apps/romm-db/romm-db.env"
    ];
    volumes = [
      "/srv/apps/romm-db:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/romm-db 0755 apps apps -"
  ];

  systemd.services.podman-romm-db.preStart = ''
    ENV_FILE="/srv/apps/romm-db/romm-db.env"

    echo "Surgically updating RomM DB env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" \
      --secrets-file "${romm-secrets}" \
      MYSQL_USER=env:ROMM_DB_USER \
      MYSQL_PASSWORD=env:ROMM_DB_PASS

    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
