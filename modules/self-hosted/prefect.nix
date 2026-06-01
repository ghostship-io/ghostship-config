{ lib, pkgs, ... }:

let
  stateDir = "/srv/apps/prefect";
  envDir = "${stateDir}/env";
  postgresEnv = "${envDir}/postgres.env";
  prefectEnv = "${envDir}/prefect.env";
  syncEnv = pkgs.writeShellScript "prefect-env-sync" ''
        set -eu

        install -d -m0750 -o root -g apps "${envDir}"
        install -d -m0755 -o apps -g apps "${stateDir}/postgres"
        install -d -m0755 -o apps -g apps "${stateDir}/redis"
        install -d -m0755 -o apps -g apps "${stateDir}/worker"

        password_file="${envDir}/postgres-password"
        if [ ! -s "$password_file" ]; then
          umask 077
          ${pkgs.openssl}/bin/openssl rand -hex 32 > "$password_file"
          chown root:apps "$password_file"
          chmod 0640 "$password_file"
        fi

        password="$(cat "$password_file")"

        umask 077
        cat > "${postgresEnv}.tmp" <<EOF
    POSTGRES_USER=prefect
    POSTGRES_PASSWORD=$password
    POSTGRES_DB=prefect
    EOF
        cat > "${prefectEnv}.tmp" <<EOF
    PREFECT_API_DATABASE_CONNECTION_URL=postgresql+asyncpg://prefect:$password@prefect-db:5432/prefect
    PREFECT_MESSAGING_BROKER=prefect_redis.messaging
    PREFECT_MESSAGING_CACHE=prefect_redis.messaging
    PREFECT_REDIS_MESSAGING_HOST=prefect-redis
    PREFECT_REDIS_MESSAGING_PORT=6379
    PREFECT_REDIS_MESSAGING_DB=0
    PREFECT_SERVER_DOCKET_URL=redis://prefect-redis:6379/1
    PREFECT_SERVER_API_HOST=0.0.0.0
    PREFECT_SERVER_UI_API_URL=https://prefect.ghostship.io/api
    PREFECT_API_URL=http://prefect:4200/api
    EOF

        chown root:apps "${postgresEnv}.tmp" "${prefectEnv}.tmp"
        chmod 0640 "${postgresEnv}.tmp" "${prefectEnv}.tmp"
        mv "${postgresEnv}.tmp" "${postgresEnv}"
        mv "${prefectEnv}.tmp" "${prefectEnv}"
  '';
  waitForDb = pkgs.writeShellScript "prefect-wait-for-db" ''
    set -eu

    for _ in $(seq 1 90); do
      if ${pkgs.podman}/bin/podman exec prefect-db pg_isready -U prefect -d prefect >/dev/null 2>&1; then
        exit 0
      fi
      sleep 2
    done

    echo "Timed out waiting for prefect-db to accept connections" >&2
    exit 1
  '';
  waitForRedis = pkgs.writeShellScript "prefect-wait-for-redis" ''
    set -eu

    for _ in $(seq 1 90); do
      if ${pkgs.podman}/bin/podman exec prefect-redis redis-cli ping >/dev/null 2>&1; then
        exit 0
      fi
      sleep 2
    done

    echo "Timed out waiting for prefect-redis to accept connections" >&2
    exit 1
  '';
  waitForServer = pkgs.writeShellScript "prefect-wait-for-server" ''
    set -eu

    for _ in $(seq 1 90); do
      if ${pkgs.podman}/bin/podman exec prefect python -c 'import urllib.request as u; u.urlopen("http://127.0.0.1:4200/api/health", timeout=2)' >/dev/null 2>&1; then
        exit 0
      fi
      sleep 2
    done

    echo "Timed out waiting for prefect server health endpoint" >&2
    exit 1
  '';
in

{
  virtualisation.oci-containers.containers = {
    "prefect-db" = {
      image = "docker.io/library/postgres:16-alpine";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=pg_isready -U prefect -d prefect || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=1m"
        "--health-on-failure=kill"
      ];
      environmentFiles = [ postgresEnv ];
      volumes = [
        "${stateDir}/postgres:/var/lib/postgresql/data:rw"
      ];
    };

    "prefect-redis" = {
      image = "docker.io/library/redis:7-alpine";
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
        "--health-start-period=30s"
        "--health-on-failure=kill"
      ];
      volumes = [
        "${stateDir}/redis:/data:rw"
      ];
    };

    "prefect" = {
      image = "docker.io/prefecthq/prefect:3-latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=python -c 'import urllib.request as u; u.urlopen(\"http://127.0.0.1:4200/api/health\", timeout=2)' || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
      ];
      cmd = [
        "prefect"
        "server"
        "start"
        "--no-services"
      ];
      environmentFiles = [ prefectEnv ];
    };

    "prefect-services" = {
      image = "docker.io/prefecthq/prefect:3-latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      extraOptions = [
        "--network=ghostship_net"
      ];
      cmd = [
        "prefect"
        "server"
        "services"
        "start"
      ];
      environmentFiles = [ prefectEnv ];
    };

    "prefect-worker" = {
      image = "docker.io/prefecthq/prefect:3-latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      extraOptions = [
        "--network=ghostship_net"
      ];
      cmd = [
        "prefect"
        "worker"
        "start"
        "--pool"
        "local-pool"
      ];
      environmentFiles = [ prefectEnv ];
      volumes = [
        "${stateDir}/worker:/root/.prefect:rw"
      ];
    };
  };

  systemd.tmpfiles.rules = [
    "d ${stateDir} 0755 apps apps -"
    "d ${envDir} 0750 root apps -"
    "d ${stateDir}/postgres 0755 apps apps -"
    "d ${stateDir}/redis 0755 apps apps -"
    "d ${stateDir}/worker 0755 apps apps -"
  ];

  systemd.services = {
    podman-prefect-db.preStart = "${syncEnv}";

    podman-prefect-redis.preStart = "${syncEnv}";

    podman-prefect = {
      after = [
        "podman-prefect-db.service"
        "podman-prefect-redis.service"
      ];
      wants = [
        "podman-prefect-db.service"
        "podman-prefect-redis.service"
      ];
      preStart = lib.mkBefore ''
        ${syncEnv}
        ${waitForDb}
        ${waitForRedis}
      '';
    };

    podman-prefect-services = {
      after = [ "podman-prefect.service" ];
      wants = [ "podman-prefect.service" ];
      preStart = lib.mkBefore ''
        ${syncEnv}
        ${waitForServer}
      '';
    };

    podman-prefect-worker = {
      after = [ "podman-prefect.service" ];
      wants = [ "podman-prefect.service" ];
      preStart = lib.mkBefore ''
        ${syncEnv}
        ${waitForServer}
      '';
    };
  };
}
