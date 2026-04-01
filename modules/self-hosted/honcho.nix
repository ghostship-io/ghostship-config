{ config, pkgs, ... }:

let
  honcho-secrets = config.sops.secrets."honcho-secrets".path;
  litellm-secrets = config.sops.secrets."litellm-secrets".path;
  honcho-env = "/srv/apps/honcho/honcho.env";
  honcho-source = pkgs.fetchFromGitHub {
    owner = "plastic-labs";
    repo = "honcho";
    rev = "f6862051672a34cfe8c5517153e92843c12c6a53";
    sha256 = "0vga50pmi8sbmsyrvj0k76dv9zs70b0xy553gaif5b6k1r3migkn";
  };
  honcho-startup = pkgs.writeShellScriptBin "honcho-startup" ''
    set -eu

    mode="''${1:-api}"
    app_root="/app"
    repo_dir="$app_root/repo"
    version_file="$repo_dir/.ghostship-honcho-version"
    source_version="v3.0.3"
    source_dir="${honcho-source}"

    ${pkgs.coreutils}/bin/mkdir -p "$app_root"
    export UV_CACHE_DIR="''${UV_CACHE_DIR:-$app_root/.uv-cache}"
    ${pkgs.coreutils}/bin/mkdir -p "$UV_CACHE_DIR"

    if [ ! -f "$version_file" ] || [ "$(${pkgs.coreutils}/bin/cat "$version_file")" != "$source_version" ]; then
      ${pkgs.coreutils}/bin/rm -rf "$repo_dir"
      ${pkgs.coreutils}/bin/mkdir -p "$repo_dir"
      ${pkgs.coreutils}/bin/cp -a "$source_dir"/. "$repo_dir"/
      ${pkgs.coreutils}/bin/printf '%s\n' "$source_version" > "$version_file"
    fi

    cd "$repo_dir"

    if [ ! -x .venv/bin/python ]; then
      uv sync --frozen --no-group dev
    fi

    wait_for_port() {
      host="$1"
      port="$2"

      python - "$host" "$port" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])

for _ in range(120):
    try:
        with socket.create_connection((host, port), timeout=2):
            raise SystemExit(0)
    except OSError:
        time.sleep(1)

raise SystemExit(1)
PY
    }

    wait_for_port honcho-db 5432
    wait_for_port honcho-redis 6379

    case "$mode" in
      api)
        .venv/bin/python scripts/provision_db.py
        exec .venv/bin/fastapi run --host 0.0.0.0 src/main.py
        ;;
      deriver)
        exec .venv/bin/python -m src.deriver
        ;;
      *)
        echo "Unknown Honcho mode: $mode" >&2
        exit 1
        ;;
    esac
  '';
  honcho-root = pkgs.buildEnv {
    name = "honcho-root";
    paths = [
      honcho-startup
      honcho-source
      pkgs.bashInteractive
      pkgs.cacert
      pkgs.coreutils
      pkgs.findutils
      pkgs.git
      pkgs.gnugrep
      pkgs.python313
      pkgs.uv
    ];
    pathsToLink = [ "/bin" ];
  };
  honcho-image = pkgs.dockerTools.buildImage {
    name = "honcho";
    tag = "latest";
    copyToRoot = honcho-root;
    config = {
      Entrypoint = [ "/bin/honcho-startup" ];
      Cmd = [ "api" ];
      WorkingDir = "/app/repo";
    };
  };
  honcho-env-sync = pkgs.writeShellScriptBin "honcho-env-sync" ''
    set -eu

    config_dir="/srv/apps/honcho"
    env_file="${honcho-env}"

    for secret_file in "${honcho-secrets}" "${litellm-secrets}"; do
      if [ ! -f "$secret_file" ]; then
        echo "Missing Honcho secret file: $secret_file" >&2
        exit 1
      fi
    done

    set -a
    . "${honcho-secrets}"
    . "${litellm-secrets}"
    set +a

    ${pkgs.coreutils}/bin/mkdir -p "$config_dir"

    cat > "$env_file" <<EOF
AUTH_USE_AUTH=false
CACHE_ENABLED=true
CACHE_URL=redis://honcho-redis:6379/0?suppress=true
DB_CONNECTION_URI=postgresql+psycopg://honcho:honcho@honcho-db:5432/honcho
DERIVER_ENABLED=true
DERIVER_PROVIDER=google
LLM_EMBEDDING_PROVIDER=gemini
LLM_GEMINI_API_KEY=$LITELLM_GEMINI_API_KEY
METRICS_ENABLED=true
EOF

    if [ -n "''${HONCHO_API_KEY:-}" ]; then
      tmp_env_file="$env_file.tmp"
      {
        ${pkgs.coreutils}/bin/printf 'HONCHO_API_KEY=%s\n' "$HONCHO_API_KEY"
        ${pkgs.coreutils}/bin/cat "$env_file"
      } > "$tmp_env_file"
      ${pkgs.coreutils}/bin/mv "$tmp_env_file" "$env_file"
    fi

    ${pkgs.coreutils}/bin/chmod 600 "$env_file"
    ${pkgs.coreutils}/bin/chown -R 3000:3000 "$config_dir"
  '';
  honcho-pre-start = pkgs.writeShellScriptBin "honcho-pre-start" ''
    set -eu

    for secret_file in "${honcho-secrets}" "${litellm-secrets}"; do
      if [ ! -f "$secret_file" ]; then
        echo "Waiting for Honcho secret file at $secret_file..."
        for _ in $(seq 1 60); do
          if [ -f "$secret_file" ]; then
            break
          fi
          sleep 1
        done
      fi

      if [ ! -f "$secret_file" ]; then
        echo "Missing Honcho secret file at $secret_file" >&2
        exit 1
      fi
    done

    ${honcho-env-sync}/bin/honcho-env-sync
  '';
  honcho-db-init = pkgs.writeText "honcho-init.sql" ''
    CREATE EXTENSION IF NOT EXISTS vector;
  '';
in
{
  virtualisation.oci-containers.containers."honcho" = {
    image = "honcho:latest";
    imageFile = honcho-image;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=python -c 'import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/health\", timeout=5).read(1)' || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=15m"
      "--health-on-failure=kill"
    ];
    environmentFiles = [
      honcho-env
    ];
    volumes = [
      "/srv/apps/honcho:/app:rw"
    ];
  };

  virtualisation.oci-containers.containers."honcho-deriver" = {
    image = "honcho:latest";
    imageFile = honcho-image;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    user = "3000:3000";
    extraOptions = [
      "--network=ghostship_net"
    ];
    cmd = [ "deriver" ];
    environmentFiles = [
      honcho-env
    ];
    volumes = [
      "/srv/apps/honcho:/app:rw"
    ];
  };

  virtualisation.oci-containers.containers."honcho-db" = {
    image = "docker.io/pgvector/pgvector:pg15";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=pg_isready -U honcho -d honcho || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    environment = {
      POSTGRES_DB = "honcho";
      POSTGRES_USER = "honcho";
      POSTGRES_PASSWORD = "honcho";
      PGDATA = "/var/lib/postgresql/data/pgdata";
    };
    cmd = [
      "postgres"
      "-c"
      "max_connections=800"
    ];
    volumes = [
      "/srv/apps/honcho-db:/var/lib/postgresql/data:rw"
      "${honcho-db-init}:/docker-entrypoint-initdb.d/init.sql:ro"
    ];
  };

  virtualisation.oci-containers.containers."honcho-redis" = {
    image = "docker.io/library/redis:8.2";
    pull = "always";
    labels = {
      "io.containers.autoupdate" = "registry";
    };
    extraOptions = [
      "--network=ghostship_net"
      "--health-cmd=redis-cli ping || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "/srv/apps/honcho-redis:/data:rw"
    ];
  };

  systemd.services.podman-honcho = {
    after = [
      "podman-honcho-db.service"
      "podman-honcho-redis.service"
    ];
    bindsTo = [
      "podman-honcho-db.service"
      "podman-honcho-redis.service"
    ];
    preStart = "${honcho-pre-start}/bin/honcho-pre-start";
  };

  systemd.services.podman-honcho-deriver = {
    after = [
      "podman-honcho.service"
      "podman-honcho-db.service"
      "podman-honcho-redis.service"
    ];
    bindsTo = [
      "podman-honcho.service"
      "podman-honcho-db.service"
      "podman-honcho-redis.service"
    ];
    preStart = "${honcho-pre-start}/bin/honcho-pre-start";
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/honcho 0755 apps apps -"
    "d /srv/apps/honcho-db 0755 apps apps -"
    "d /srv/apps/honcho-redis 0755 apps apps -"
  ];
}
