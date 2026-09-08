{
  config,
  lib,
  pkgs,
  ...
}:

let
  grimmory-secrets = config.ghostship.selfHostedSecrets.projections.grimmory.path;
in
{
  ghostship.apps.grimmory = {
    healthPath = "/api/v1/healthcheck";
    name = "Grimmory";
    group = "Media";
    description = "Ebook Manager";
    icon = "sh-booklore";
    order = 90;
    hostname = "grimmory.ghostship.io";
    origin = "http://grimmory:6060";
    widget = {
      type = "booklore";
      username = "env:GRIMMORY_USER";
      password = "env:GRIMMORY_PASS";
    };
    muximux = {
      icon = "muximux-book2";
      color = "#49da7e";
      dropdown = false;
      url = "/grimmory/";
    };
  };

  virtualisation.oci-containers.containers."grimmory" = {
    podman.sdnotify = "healthy";
    image = "docker.io/grimmory/grimmory:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q -O /dev/null --tries=1 --timeout=5 http://127.0.0.1:6060/api/v1/healthcheck || exit 1"
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
      "/mnt/share/Library/Books:/books:rw"
      "/mnt/share/Library/Audiobooks:/audiobooks:rw"
      "/mnt/share/Library/Books/.bookdrop:/bookdrop:rw"
    ];
  };

  systemd.services.podman-grimmory = {
    after = [
      "mnt-share.mount"
      "podman-grimmory-db.service"
    ];
    wants = [
      "mnt-share.mount"
      "podman-grimmory-db.service"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/grimmory 0700 apps apps -"
    "d /srv/apps/grimmory/data 0755 apps apps -"
  ];

  systemd.services.podman-grimmory.preStart = lib.mkAfter ''
    ENV_FILE="/srv/apps/grimmory/grimmory.env"
    SECRETS_FILE="${grimmory-secrets}"
    if [ ! -s "$SECRETS_FILE" ]; then
      echo "Missing required service credentials" >&2
      exit 1
    fi
    if [ -f "$SECRETS_FILE" ]; then
      echo "Surgically updating Grimmory env file..."
      set -a
      . "$SECRETS_FILE"
      set +a
      mkdir -p "$(dirname "$ENV_FILE")"
      touch "$ENV_FILE"

      grimmory_args=(
        --require-secrets
        DATABASE_USERNAME=env:GRIMMORY_DB_USER
        DATABASE_PASSWORD=env:GRIMMORY_DB_PASS
      )

      ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${grimmory_args[@]}"
      chown 3000:3000 "$ENV_FILE"
      chmod 600 "$ENV_FILE"
    fi
  '';
}
