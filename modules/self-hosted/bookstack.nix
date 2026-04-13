{ config, lib, pkgs, ... }:

let
  bookstack-secrets = config.ghostship.selfHostedSecrets.units."bookstack-secrets".path;
in
{
  virtualisation.oci-containers.containers."bookstack" = {
    image = "lscr.io/linuxserver/bookstack:latest";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=wget -q --spider --tries=1 --timeout=5 http://127.0.0.1/login || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    environment = {
      PUID = "3000";
      PGID = "3000";
      TZ = "UTC";
    };
    environmentFiles = [
      "/srv/apps/bookstack/bookstack.env"
    ];
    volumes = [
      "/srv/apps/bookstack:/config:rw"
    ];
  };

  systemd.services.podman-bookstack = {
    after = [ "podman-bookstack-db.service" ];
    requires = [ "podman-bookstack-db.service" ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/bookstack 0755 apps apps -"
  ];

  systemd.services.podman-bookstack.preStart = ''
    ENV_FILE="/srv/apps/bookstack/bookstack.env"

    if [ ! -f "${bookstack-secrets}" ]; then
      echo "Missing BookStack secrets file: ${bookstack-secrets}" >&2
      exit 1
    fi

    echo "Surgically updating BookStack env file..."
    set -a
    . "${bookstack-secrets}"
    set +a

    mkdir -p "$(dirname "$ENV_FILE")"
    touch "$ENV_FILE"

    bookstack_args=(
      APP_KEY=env:BOOKSTACK_APP_KEY
      APP_URL=env:BOOKSTACK_APP_URL
      DB_HOST=literal:bookstack-db
      DB_PORT=literal:3306
      DB_DATABASE=env:BOOKSTACK_DB_DATABASE
      DB_USERNAME=env:BOOKSTACK_DB_USER
      DB_PASSWORD=env:BOOKSTACK_DB_PASS
    )

    ${pkgs.ghostship-config}/bin/ghostship-config set "$ENV_FILE" "''${bookstack_args[@]}"
    chown 3000:3000 "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  '';
}
