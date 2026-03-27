{ config, lib, pkgs, ... }:

let
  grimmory-secrets = config.sops.secrets."grimmory-secrets".path;
in
{
  virtualisation.oci-containers.containers."grimmory" = {
    image = "grimmory/grimmory:latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=/bin/sh -c 'for _ in $(seq 1 45); do wget -q --spider http://127.0.0.1:6060 && exit 0; sleep 2; done; exit 1'"
      "--health-interval=1m"
      "--health-timeout=100s"
      "--health-retries=3"
      "--health-start-period=45s"
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
        ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" \
          DATABASE_USERNAME=env:GRIMMORY_DB_USER \
          DATABASE_PASSWORD=env:GRIMMORY_DB_PASSWORD
        chown 3000:3000 "$ENV_FILE"
        chmod 600 "$ENV_FILE"
      fi
    '';
  };
}
