{ config, lib, pkgs, ... }:

let
  bookstack-secrets = config.sops.secrets."bookstack-secrets".path;
in
{
  virtualisation.oci-containers.containers."bookstack-db" = {
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
    };
    environmentFiles = [
      "/srv/apps/bookstack-db/bookstack-db.env"
    ];
    volumes = [
      "/srv/apps/bookstack-db:/var/lib/mysql:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/bookstack-db 0755 apps apps -"
  ];

  systemd.services.podman-bookstack-db.preStart = ''
    ENV_FILE="/srv/apps/bookstack-db/bookstack-db.env"

    if [ ! -f "${bookstack-secrets}" ]; then
      echo "Missing BookStack secrets file: ${bookstack-secrets}" >&2
      exit 1
    fi

    echo "Surgically updating BookStack DB env file..."
    set -a
    . "${bookstack-secrets}"
    set +a

    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    bookstack_db_args=(
      MYSQL_DATABASE=env:BOOKSTACK_DB_DATABASE
      MYSQL_USER=env:BOOKSTACK_DB_USER
      MYSQL_PASSWORD=env:BOOKSTACK_DB_PASS
      MYSQL_ROOT_PASSWORD=env:BOOKSTACK_DB_ROOT_PASS
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${bookstack_db_args[@]}"
    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
