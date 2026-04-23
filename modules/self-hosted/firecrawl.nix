{ config, lib, pkgs, ... }:

let
  firecrawl-root = "/srv/apps/firecrawl";
  firecrawl-secrets = config.ghostship.selfHostedSecrets.units."firecrawl-secrets".path;
  firecrawl-runtime-env = config.ghostship.selfHostedSecrets.projections."firecrawl-runtime".path;
  render-firecrawl-runtime = "${config.ghostship.selfHostedSecrets.render}/bin/ghostship-secret-project firecrawl-runtime";
  containers-root = ../../containers;
  containers-root-str = toString containers-root;
  containers-hash = builtins.substring 11 12 containers-root-str;
  firecrawl-playwright-image = "localhost/ghostship-firecrawl-playwright-cloakbrowser:${containers-hash}";
  firecrawl-playwright-build = pkgs.writeShellScriptBin "ghostship-build-firecrawl-playwright-image" ''
    set -eu

    image="${firecrawl-playwright-image}"
    dockerfile="${containers-root}/firecrawl-playwright-cloakbrowser/Dockerfile"
    context_dir="${containers-root}"

    if ${pkgs.podman}/bin/podman image exists "$image"; then
      exit 0
    fi

    ${pkgs.podman}/bin/podman build \
      --pull=always \
      --tag "$image" \
      --file "$dockerfile" \
      "$context_dir"
  '';
  firecrawl-runtime-sync = pkgs.writeShellScriptBin "firecrawl-runtime-sync" ''
    set -eu

    if [ ! -f "${firecrawl-secrets}" ]; then
      echo "Waiting for Firecrawl secrets at ${firecrawl-secrets}..."
      for _ in $(seq 1 30); do
        if [ -f "${firecrawl-secrets}" ]; then
          break
        fi
        sleep 1
      done
    fi

    if [ ! -f "${firecrawl-secrets}" ]; then
      echo "Missing Firecrawl secrets file at ${firecrawl-secrets}" >&2
      exit 1
    fi

    ${render-firecrawl-runtime}
  '';
in
{
  virtualisation.oci-containers.containers = {
    "firecrawl-playwright" = {
      image = firecrawl-playwright-image;
      pull = "never";
      labels = {
        "io.containers.autoupdate" = "disabled";
      };
      extraOptions = [
        "--network=ghostship_net"
        ''--health-cmd=node -e "fetch('http://127.0.0.1:3000/health').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))" || exit 1''
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
        "--tmpfs=/tmp/.cache:rw,noexec,nosuid,size=1g"
      ];
      environment = {
        PORT = "3000";
        USE_CLOAKBROWSER = "true";
        CLOAKBROWSER_HUMANIZE = "true";
      };
    };

    "firecrawl-api" = {
      image = "ghcr.io/firecrawl/firecrawl:latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      cmd = [ "node" "dist/src/harness.js" "--start-docker" ];
      environmentFiles = [ firecrawl-runtime-env ];
      environment = {
        HOST = "0.0.0.0";
        PORT = "3002";
        USE_DB_AUTHENTICATION = "false";
        PLAYWRIGHT_MICROSERVICE_URL = "http://firecrawl-playwright:3000/scrape";
        REDIS_URL = "redis://firecrawl-redis:6379";
        REDIS_RATE_LIMIT_URL = "redis://firecrawl-redis:6379";
        NUQ_RABBITMQ_URL = "amqp://firecrawl-rabbitmq:5672";
        POSTGRES_HOST = "firecrawl-postgres";
        POSTGRES_PORT = "5432";
        POSTGRES_USER = "firecrawl";
        POSTGRES_DB = "firecrawl";
        SEARXNG_ENDPOINT = "http://searxng:8080";
        OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/";
        MODEL_NAME = "gemini-2.5-flash-lite";
      };
      extraOptions = [
        "--network=ghostship_net"
        ''--health-cmd=node -e "fetch('http://127.0.0.1:3002/e2e-test').then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))" || exit 1''
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
      ];
    };

    "firecrawl-postgres" = {
      image = "docker.io/library/postgres:16";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      environmentFiles = [ firecrawl-runtime-env ];
      environment = {
        POSTGRES_USER = "firecrawl";
        POSTGRES_DB = "firecrawl";
      };
      volumes = [
        "${firecrawl-root}/postgres:/var/lib/postgresql/data:rw"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=pg_isready -U firecrawl -h 127.0.0.1 || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
    };

    "firecrawl-rabbitmq" = {
      image = "docker.io/library/rabbitmq:3-management";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      volumes = [
        "${firecrawl-root}/rabbitmq:/var/lib/rabbitmq:rw"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=rabbitmq-diagnostics -q check_running"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
    };

    "firecrawl-redis" = {
      image = "docker.io/library/redis:alpine";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      cmd = [ "redis-server" "--bind" "0.0.0.0" ];
      volumes = [
        "${firecrawl-root}/redis:/data:rw"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=redis-cli -h 127.0.0.1 ping | grep -q PONG || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
    };
  };

  systemd.services = {
    podman-firecrawl-playwright.preStart = lib.mkBefore ''
      ${firecrawl-playwright-build}/bin/ghostship-build-firecrawl-playwright-image
    '';

    podman-firecrawl-api = {
      after = [
        "podman-firecrawl-playwright.service"
        "podman-firecrawl-postgres.service"
        "podman-firecrawl-rabbitmq.service"
        "podman-firecrawl-redis.service"
      ];
      wants = [
        "podman-firecrawl-playwright.service"
        "podman-firecrawl-postgres.service"
        "podman-firecrawl-rabbitmq.service"
        "podman-firecrawl-redis.service"
      ];
      requires = [
        "podman-firecrawl-playwright.service"
        "podman-firecrawl-postgres.service"
        "podman-firecrawl-rabbitmq.service"
        "podman-firecrawl-redis.service"
      ];
      preStart = lib.mkBefore ''
        ${firecrawl-runtime-sync}/bin/firecrawl-runtime-sync
      '';
    };

    podman-firecrawl-postgres.preStart = lib.mkBefore ''
      ${firecrawl-runtime-sync}/bin/firecrawl-runtime-sync
    '';
  };

  systemd.tmpfiles.rules = [
    "d ${firecrawl-root} 0755 apps apps -"
    "d ${firecrawl-root}/postgres 0755 apps apps -"
    "d ${firecrawl-root}/rabbitmq 0755 apps apps -"
    "d ${firecrawl-root}/redis 0755 apps apps -"
  ];
}
