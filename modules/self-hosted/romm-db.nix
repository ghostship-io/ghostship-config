{
  config,
  lib,
  pkgs,
  ...
}:

let
  romm-secrets = config.ghostship.selfHostedSecrets.projections."romm-db".path;
in
{
  virtualisation.oci-containers.containers."romm-db" = {
    podman.sdnotify = "healthy";
    image = "lscr.io/linuxserver/mariadb@sha256:94f67a7e6deb4557630c9aaba08142eb2f667101d9bc6069167ae3ae21502e90";
    pull = "always";
    # Preserve the live database engine until a restore-tested migration is reviewed.
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
      MYSQL_ALLOW_EMPTY_PASSWORD = "yes";
      MYSQL_DATABASE = "romm";
      CLI_OPTS = "--log-bin-trust-function-creators=1";
    };
    environmentFiles = [
      "/srv/apps/romm-db/romm-db.env"
    ];
    volumes = [
      "/srv/apps/romm-db:/config:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/romm-db 0700 apps apps -"
  ];

  systemd.services.podman-romm-db.preStart = ''
    ENV_FILE="/srv/apps/romm-db/romm-db.env"

    echo "Surgically updating RomM DB env file..."
    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    romm_db_args=(
      --secrets-file "${romm-secrets}"
      MYSQL_USER=env:ROMM_DB_USER
      MYSQL_PASSWORD=env:ROMM_DB_PASS
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${romm_db_args[@]}"

    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
