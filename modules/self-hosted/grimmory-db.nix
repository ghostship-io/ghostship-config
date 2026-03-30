{ config, lib, pkgs, ... }:

let
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
in
{
  virtualisation.oci-containers.containers."grimmory-db" = {
    image = "docker.io/library/mariadb:11";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=mariadb-admin ping -h 127.0.0.1 || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
      MYSQL_ROOT_HOST = "127.0.0.1";
      MYSQL_DATABASE = "grimmory";
    };
    environmentFiles = [
      "/srv/apps/grimmory-db/grimmory-db.env"
    ];
    volumes = [
      "/srv/apps/grimmory-db:/var/lib/mysql:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/grimmory-db 0755 apps apps -"
  ];

  system.activationScripts.grimmory-db-config = {
    text = ''
      ENV_FILE="/srv/apps/grimmory-db/grimmory-db.env"
      SECRETS_FILE="${grimmory-secrets}"
      if [ -f "$SECRETS_FILE" ]; then
        echo "Surgically updating Grimmory DB env file..."
        set -a
        . "$SECRETS_FILE"
        set +a
        mkdir -p "$(dirname "$ENV_FILE")"
        touch "$ENV_FILE"

        grimmory_db_args=(
          MYSQL_USER=env:GRIMMORY_DB_USER
          MYSQL_PASSWORD=env:GRIMMORY_DB_PASS
          MYSQL_ROOT_PASSWORD=env:GRIMMORY_MYSQL_ROOT_PASS
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${grimmory_db_args[@]}"
        chown 3000:3000 "$ENV_FILE"
        chmod 600 "$ENV_FILE"
      fi
    '';
  };
}
