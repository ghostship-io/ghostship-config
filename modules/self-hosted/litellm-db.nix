{ config, pkgs, ... }:

let
  litellm-secrets = config.sops.secrets."litellm-secrets".path;
  litellm-db-runtime-env = "/run/secrets/litellm-db-runtime.env";
in

{
  virtualisation.oci-containers.containers."litellm-db" = {
    image = "docker.io/library/postgres:16-alpine";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=pg_isready -U litellm"
      "--health-interval=10s"
      "--health-timeout=5s"
      "--health-retries=5"
      "--health-start-period=30s"
    ];
    environment = {
      POSTGRES_USER = "litellm";
      POSTGRES_DB = "litellm";
    };
    environmentFiles = [
      litellm-secrets
      litellm-db-runtime-env
    ];
    volumes = [
      "/srv/apps/litellm-db:/var/lib/postgresql/data"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm-db 0755 apps apps -"
  ];

  systemd.services.podman-litellm-db.preStart = ''
    if [ ! -f "${litellm-secrets}" ]; then
      echo "Waiting for LiteLLM secrets at ${litellm-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${litellm-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${litellm-secrets}" ]; then
      echo "Missing LiteLLM secrets file at ${litellm-secrets}" >&2
      exit 1
    fi

    set -a
    . "${litellm-secrets}"
    set +a

    if [ -z "''${LITELLM_DB_PASS:-}" ]; then
      echo "Missing LITELLM_DB_PASS in ${litellm-secrets}" >&2
      exit 1
    fi

    mkdir -p /run/secrets
    cat > ${litellm-db-runtime-env} <<EOF
POSTGRES_PASSWORD=$LITELLM_DB_PASS
EOF
    chmod 600 ${litellm-db-runtime-env}
  '';

  systemd.services.podman-litellm-db.postStart = ''
    set -a
    . "${litellm-secrets}"
    set +a

    for _ in $(seq 1 30); do
      if ${pkgs.podman}/bin/podman exec litellm-db pg_isready -U litellm >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done

    ${pkgs.podman}/bin/podman exec -i litellm-db \
      psql -U litellm -d litellm -v ON_ERROR_STOP=1 \
      --set=password="$LITELLM_DB_PASS" <<'SQL'
ALTER ROLE litellm WITH PASSWORD :'password';
SQL
  '';
}
