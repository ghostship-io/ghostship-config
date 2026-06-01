{ config, lib, pkgs, ... }:

let
  stateDir = "/srv/apps/hatchet";
  envDir = "${stateDir}/env";
  postgresEnv = "${envDir}/postgres.env";
  hatchetEnv = "${envDir}/hatchet.env";
  syncEnv = pkgs.writeShellScript "hatchet-env-sync" ''
    set -eu

    install -d -m0750 -o root -g apps "${envDir}"
    install -d -m0755 -o apps -g apps "${stateDir}/postgres"
    install -d -m0755 -o apps -g apps "${stateDir}/config"
    install -d -m0755 -o apps -g apps "${stateDir}/certs"

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
POSTGRES_USER=hatchet
POSTGRES_PASSWORD=$password
POSTGRES_DB=hatchet
EOF
    cat > "${hatchetEnv}.tmp" <<EOF
DATABASE_URL=postgres://hatchet:$password@hatchet-db:5432/hatchet
SERVER_MSGQUEUE_KIND=postgres
SERVER_AUTH_COOKIE_DOMAIN=hatchet.ghostship.io
SERVER_AUTH_COOKIE_INSECURE=t
SERVER_GRPC_BIND_ADDRESS=0.0.0.0
SERVER_GRPC_INSECURE=t
SERVER_GRPC_BROADCAST_ADDRESS=hatchet-engine:7070
SERVER_DEFAULT_ENGINE_VERSION=V1
SERVER_INTERNAL_CLIENT_INTERNAL_GRPC_BROADCAST_ADDRESS=hatchet-engine:7070
EOF

    chown root:apps "${postgresEnv}.tmp" "${hatchetEnv}.tmp"
    chmod 0640 "${postgresEnv}.tmp" "${hatchetEnv}.tmp"
    mv "${postgresEnv}.tmp" "${postgresEnv}"
    mv "${hatchetEnv}.tmp" "${hatchetEnv}"
  '';
  waitForDb = pkgs.writeShellScript "hatchet-wait-for-db" ''
    set -eu

    for _ in $(seq 1 90); do
      if ${pkgs.podman}/bin/podman exec hatchet-db pg_isready -U hatchet -d hatchet >/dev/null 2>&1; then
        exit 0
      fi
      sleep 2
    done

    echo "Timed out waiting for hatchet-db to accept connections" >&2
    exit 1
  '';
  runSetup = pkgs.writeShellScript "hatchet-setup" ''
    set -eu

    ${syncEnv}
    ${waitForDb}

    ${pkgs.podman}/bin/podman run --rm \
      --network=ghostship_net \
      --env-file "${hatchetEnv}" \
      ghcr.io/hatchet-dev/hatchet/hatchet-migrate:latest \
      /hatchet/hatchet-migrate

    ${pkgs.podman}/bin/podman run --rm \
      --network=ghostship_net \
      --env-file "${hatchetEnv}" \
      --volume "${stateDir}/config:/hatchet/config:rw" \
      --volume "${stateDir}/certs:/hatchet/certs:rw" \
      ghcr.io/hatchet-dev/hatchet/hatchet-admin:latest \
      /hatchet/hatchet-admin quickstart --skip certs --generated-config-dir /hatchet/config --overwrite=false
  '';
in

{
  virtualisation.oci-containers.containers = {
    "hatchet-db" = {
      image = "docker.io/library/postgres:15.6-alpine";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      cmd = [
        "postgres"
        "-c"
        "max_connections=1000"
      ];
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=pg_isready -U hatchet -d hatchet || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=1m"
        "--health-on-failure=kill"
        "--shm-size=1g"
      ];
      environmentFiles = [ postgresEnv ];
      volumes = [
        "${stateDir}/postgres:/var/lib/postgresql/data:rw"
      ];
    };

    "hatchet-engine" = {
      image = "ghcr.io/hatchet-dev/hatchet/hatchet-engine:latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      cmd = [
        "/hatchet/hatchet-engine"
        "--config"
        "/hatchet/config"
      ];
      extraOptions = [
        "--network=ghostship_net"
      ];
      environmentFiles = [ hatchetEnv ];
      volumes = [
        "${stateDir}/config:/hatchet/config:ro"
        "${stateDir}/certs:/hatchet/certs:ro"
      ];
    };

    "hatchet" = {
      image = "ghcr.io/hatchet-dev/hatchet/hatchet-dashboard:latest";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      cmd = [
        "sh"
        "./entrypoint.sh"
        "--config"
        "/hatchet/config"
      ];
      extraOptions = [
        "--network=ghostship_net"
      ];
      environmentFiles = [ hatchetEnv ];
      volumes = [
        "${stateDir}/config:/hatchet/config:ro"
        "${stateDir}/certs:/hatchet/certs:ro"
      ];
    };
  };

  systemd.tmpfiles.rules = [
    "d ${stateDir} 0755 apps apps -"
    "d ${envDir} 0750 root apps -"
    "d ${stateDir}/postgres 0755 apps apps -"
    "d ${stateDir}/config 0755 apps apps -"
    "d ${stateDir}/certs 0755 apps apps -"
  ];

  systemd.services = {
    podman-hatchet-db.preStart = "${syncEnv}";

    hatchet-setup = {
      description = "Prepare Hatchet database and generated config";
      after = [ "podman-hatchet-db.service" ];
      wants = [ "podman-hatchet-db.service" ];
      path = [ config.virtualisation.podman.package ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = "${runSetup}";
    };

    podman-hatchet-engine = {
      after = [
        "podman-hatchet-db.service"
        "hatchet-setup.service"
      ];
      wants = [
        "podman-hatchet-db.service"
        "hatchet-setup.service"
      ];
    };

    podman-hatchet = {
      after = [
        "podman-hatchet-engine.service"
        "hatchet-setup.service"
      ];
      wants = [
        "podman-hatchet-engine.service"
        "hatchet-setup.service"
      ];
    };
  };
}
