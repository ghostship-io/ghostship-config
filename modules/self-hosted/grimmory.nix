{ config, lib, pkgs, ... }:

let
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
in
{
  virtualisation.oci-containers.containers."grimmory" = {
    image = "grimmory/grimmory:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1:6060/ || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      TZ = "UTC";
      DATABASE_URL = "jdbc:mariadb://grimmory-db:3306/grimmory";
      USER_ID = "3000";
      GROUP_ID = "3000";
      GRIMMORY_PORT = "6060";
    };
    environmentFiles = [
      "/srv/apps/grimmory/grimmory.env"
    ];
    volumes = [
      "/srv/apps/grimmory/data:/app/data:rw"
      "/mnt/share/Library/Books:/app/books:rw"
      "/mnt/share/Library/Books/.bookdrop:/app/bookdrop:rw"
    ];
  };

  systemd.services.podman-grimmory = {
    after = [ "mnt-share.mount" "podman-grimmory-db.service" ];
    wants = [ "mnt-share.mount" "podman-grimmory-db.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/grimmory 0755 apps apps -"
    "d /srv/apps/grimmory/data 0755 apps apps -"
  ];

  system.activationScripts.grimmory-config = {
    text = ''
      ENV_FILE="/srv/apps/grimmory/grimmory.env"
      SECRETS_FILE="${grimmory-secrets}"
      if [ -f "$SECRETS_FILE" ]; then
        echo "Surgically updating Grimmory env file..."
        set -a
        . "$SECRETS_FILE"
        set +a
        mkdir -p "$(dirname "$ENV_FILE")"
        touch "$ENV_FILE"

        grimmory_args=(
          DATABASE_USERNAME=env:GRIMMORY_DB_USER
          DATABASE_PASSWORD=env:GRIMMORY_DB_PASS
        )

        ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${grimmory_args[@]}"
        chown 3000:3000 "$ENV_FILE"
        chmod 600 "$ENV_FILE"
      fi
    '';
  };
}
