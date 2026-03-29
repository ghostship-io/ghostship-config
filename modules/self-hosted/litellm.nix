{ config, ... }:

let
  litellm-secrets = config.sops.secrets."litellm-secrets".path;
  litellm-runtime-env = "/run/secrets/litellm-runtime.env";
  litellm-chatgpt-token-dir = "/root/.config/litellm/chatgpt";
in

{
  virtualisation.oci-containers.containers."litellm" = {
    image = "ghcr.io/berriai/litellm:main-latest";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=python3 -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/health/readiness')\" || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      LITELLM_LOG = "ERROR";
      LITELLM_MODE = "PRODUCTION";
      STORE_MODEL_IN_DB = "True";
      USE_PRISMA_MIGRATE = "True";
      PROXY_BATCH_WRITE_AT = "60";
      DATABASE_CONNECTION_POOL_LIMIT = "10";
      ALLOW_REQUESTS_ON_DB_UNAVAILABLE = "True";
      DISABLE_LOAD_DOTENV = "True";
      LITELLM_MIGRATION_DIR = "/app/migrations";
      CHATGPT_TOKEN_DIR = litellm-chatgpt-token-dir;
    };
    cmd = [
      "--port" "4000"
      "--num_workers" "1"
    ];
    environmentFiles = [
      litellm-secrets
      litellm-runtime-env
    ];
    volumes = [
      "/srv/apps/litellm/chatgpt:${litellm-chatgpt-token-dir}"
    ];
  };

  systemd.services.podman-litellm = {
    after = [ "podman-litellm-db.service" ];
    wants = [ "podman-litellm-db.service" ];
  };

  systemd.services.podman-litellm.preStart = ''
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

    if [ -z "''${LITELLM_DATABASE_URL:-}" ]; then
      echo "Missing LITELLM_DATABASE_URL in ${litellm-secrets}" >&2
      exit 1
    fi

    mkdir -p /run/secrets
    cat > ${litellm-runtime-env} <<EOF
DATABASE_URL=$LITELLM_DATABASE_URL
EOF
    chmod 600 ${litellm-runtime-env}
  '';

  systemd.tmpfiles.rules = [
    "d /srv/apps/litellm 0755 apps apps -"
    "d /srv/apps/litellm/chatgpt 0700 root root -"
  ];
}
