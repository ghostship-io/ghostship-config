{ lib, pkgs, ... }:

let
  imageName = "localhost/ghostship-windmill";
  imageTag = "1.601.1-lg-page-14";
  windmillPackage = pkgs.windmill.overrideAttrs (old: {
    env = old.env // {
      JEMALLOC_SYS_WITH_LG_PAGE = "14";
    };
  });
  windmillImage = pkgs.dockerTools.buildLayeredImage {
    name = imageName;
    tag = imageTag;
    contents = [
      windmillPackage
      pkgs.curl
      pkgs.util-linux
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.dockerTools.caCertificates
    ];
    extraCommands = ''
      mkdir -p etc root tmp
      chmod 1777 tmp
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      EOF
    '';
    config = {
      Cmd = [ "${windmillPackage}/bin/windmill" ];
      Env = [
        "HOME=/root"
        "PATH=/bin:/usr/bin:${windmillPackage}/bin:${pkgs.curl}/bin:${pkgs.util-linux}/bin"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      ];
      ExposedPorts = {
        "8000/tcp" = { };
      };
    };
  };
  stateDir = "/srv/apps/windmill";
  envDir = "${stateDir}/env";
  postgresEnv = "${envDir}/postgres.env";
  windmillEnv = "${envDir}/windmill.env";
  syncEnv = pkgs.writeShellScript "windmill-env-sync" ''
        set -eu

        install -d -m0750 -o root -g apps "${envDir}"
        install -d -m0755 -o apps -g apps "${stateDir}/postgres"
        install -d -m0755 -o apps -g apps "${stateDir}/worker-cache"

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
    POSTGRES_USER=windmill
    POSTGRES_PASSWORD=$password
    POSTGRES_DB=windmill
    EOF
        cat > "${windmillEnv}.tmp" <<EOF
    DATABASE_URL=postgres://windmill:$password@windmill-db:5432/windmill?sslmode=disable
    BASE_URL=https://windmill.ghostship.io
    WM_BASE_URL=https://windmill.ghostship.io
    RUST_LOG=info
    DISABLE_NSJAIL=true
    ENABLE_UNSHARE_PID=true
    EOF

        chown root:apps "${postgresEnv}.tmp" "${windmillEnv}.tmp"
        chmod 0640 "${postgresEnv}.tmp" "${windmillEnv}.tmp"
        mv "${postgresEnv}.tmp" "${postgresEnv}"
        mv "${windmillEnv}.tmp" "${windmillEnv}"
  '';
  waitForDb = pkgs.writeShellScript "windmill-wait-for-db" ''
    set -eu

    for _ in $(seq 1 90); do
      if ${pkgs.podman}/bin/podman exec windmill-db pg_isready -U windmill -d windmill >/dev/null 2>&1; then
        exit 0
      fi
      sleep 2
    done

    echo "Timed out waiting for windmill-db to accept connections" >&2
    exit 1
  '';
in

{
  virtualisation.oci-containers.containers = {
    "windmill-db" = {
      image = "docker.io/library/postgres:16-alpine";
      pull = "always";
      labels = {
        "io.containers.autoupdate" = "registry";
      };
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=pg_isready -U windmill -d windmill || exit 1"
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

    "windmill" = {
      image = "${imageName}:${imageTag}";
      imageFile = windmillImage;
      pull = "never";
      labels = {
        "io.containers.autoupdate" = "disabled";
      };
      extraOptions = [
        "--network=ghostship_net"
        "--health-cmd=curl -fsS http://127.0.0.1:8000/ >/dev/null || exit 1"
        "--health-interval=30s"
        "--health-timeout=10s"
        "--health-retries=5"
        "--health-start-period=2m"
        "--health-on-failure=kill"
      ];
      environment = {
        MODE = "server";
      };
      environmentFiles = [ windmillEnv ];
    };

    "windmill-worker" = {
      image = "${imageName}:${imageTag}";
      imageFile = windmillImage;
      pull = "never";
      labels = {
        "io.containers.autoupdate" = "disabled";
      };
      extraOptions = [
        "--network=ghostship_net"
      ];
      environment = {
        MODE = "worker";
        WORKER_GROUP = "default";
      };
      environmentFiles = [ windmillEnv ];
      volumes = [
        "${stateDir}/worker-cache:/tmp/windmill/cache:rw"
      ];
    };
  };

  systemd.tmpfiles.rules = [
    "d ${stateDir} 0755 apps apps -"
    "d ${envDir} 0750 root apps -"
    "d ${stateDir}/postgres 0755 apps apps -"
    "d ${stateDir}/worker-cache 0755 apps apps -"
  ];

  systemd.services = {
    podman-windmill-db.preStart = "${syncEnv}";

    podman-windmill = {
      after = [ "podman-windmill-db.service" ];
      wants = [ "podman-windmill-db.service" ];
      preStart = lib.mkBefore ''
        ${syncEnv}
        ${waitForDb}
      '';
    };

    podman-windmill-worker = {
      after = [ "podman-windmill-db.service" ];
      wants = [ "podman-windmill-db.service" ];
      preStart = lib.mkBefore ''
        ${syncEnv}
        ${waitForDb}
      '';
    };
  };
}
