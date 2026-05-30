{
  inputs,
  lib,
  pkgs,
  ...
}:

let
  codexHome = "/srv/apps/codex/home";
  codexNix = "/srv/apps/codex/nix";
  codexDocker = "/srv/apps/codex/docker";
  codexWorkspace = "/srv/apps/codex/workspace";
  imageName = "localhost/ghostship-codex";
  imageTag = "codex-web-${inputs.codex-web.shortRev or inputs.codex-web.rev}";
  system = pkgs.stdenv.hostPlatform.system;

  codexWeb = inputs.codex-web.packages.${system}.default;
  codexWebCli = inputs.codex-web.packages.${system}.codex;

  codexPackages = with pkgs; [
    codexWeb
    codexWebCli
    nix
    docker
    git
    gh
    openssh
    curl
    jq
    ripgrep
    fd
    direnv
    uv
    python3
    nodejs_24
    stdenv.cc
    gnumake
    pkg-config
    cmake
    binutils
    coreutils
    findutils
    gnugrep
    gnused
    gnutar
    gzip
    unzip
    iptables
    iproute2
    kmod
    shadow
    which
    file
    bashInteractive
    cacert
  ];

  codexPath = lib.makeBinPath codexPackages;

  codexEntrypoint = pkgs.writeShellScriptBin "codex-web-entrypoint" ''
    set -eu

    export HOME=/home/codex
    export USER=codex
    export PATH=${codexPath}:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export CODEX_CLI_PATH=${codexWebCli}/bin/codex

    mkdir -p "$HOME" /workspace /mnt/share /var/lib/docker /var/run /tmp

    rm -f /var/run/docker.pid
    dockerd \
      --host=unix:///var/run/docker.sock \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none &
    docker_pid=$!
    trap 'kill "$docker_pid" 2>/dev/null || true' EXIT

    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done

    cd /workspace

    exec ${codexWeb}/bin/codex-web --host 0.0.0.0 --port 8214
  '';

  codexImage = pkgs.dockerTools.buildLayeredImage {
    name = imageName;
    tag = imageTag;
    contents = codexPackages ++ [
      codexEntrypoint
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.dockerTools.caCertificates
    ];
    extraCommands = ''
      mkdir -p etc tmp workspace home/codex
      mkdir -p mnt/share var/lib/docker var/run
      chmod 1777 tmp
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      codex:x:3000:3000:Codex:/home/codex:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      codex:x:3000:
      EOF
      cat > etc/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      EOF
    '';
    config = {
      Cmd = [ "${codexEntrypoint}/bin/codex-web-entrypoint" ];
      Env = [
        "HOME=/home/codex"
        "USER=codex"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "PATH=${codexPath}"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "CODEX_CLI_PATH=${codexWebCli}/bin/codex"
      ];
      WorkingDir = "/workspace";
      ExposedPorts = {
        "8214/tcp" = { };
      };
    };
  };
in
{
  virtualisation.oci-containers.containers."codex" = {
    image = "${imageName}:${imageTag}";
    imageFile = codexImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--network=ghostship_net"
      "--health-cmd=curl -fsS http://127.0.0.1:8214/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=1m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${codexNix}:/nix:rw"
      "${codexDocker}:/var/lib/docker:rw"
      "${codexWorkspace}:/workspace:rw"
      "${codexHome}:/home/codex:rw"
      "/mnt/share:/mnt/share:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/codex 0755 root root -"
    "d ${codexDocker} 0755 root root -"
    "d ${codexHome} 0755 3000 3000 -"
    "d ${codexWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-codex = {
    after = [ "init-ghostship-net.service" ];
    wants = [ "init-ghostship-net.service" ];
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/codex
      install -d -m0755 -o root -g root ${codexDocker}
      install -d -m0755 -o 3000 -g 3000 ${codexHome}
      install -d -m0755 -o 3000 -g 3000 ${codexWorkspace}

      if [ ! -e ${codexNix}/.ghostship-seeded-image ] || [ "$(<${codexNix}/.ghostship-seeded-image)" != "${codexImage}" ]; then
        ${pkgs.podman}/bin/podman load -i ${codexImage}

        seed_container="codex-nix-seed-$$"
        seed_tmp="${codexNix}.seed.$$"
        rm -rf "$seed_tmp"
        mkdir -p "$seed_tmp"

        ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null 2>&1 || true
        ${pkgs.podman}/bin/podman create --pull=never --name "$seed_container" "${imageName}:${imageTag}" >/dev/null
        ${pkgs.podman}/bin/podman cp "$seed_container:/nix/." "$seed_tmp/"
        ${pkgs.podman}/bin/podman rm -f "$seed_container" >/dev/null

        if [ -e ${codexNix} ]; then
          cp -a "$seed_tmp"/. ${codexNix}/
          rm -rf "$seed_tmp"
        else
          mv "$seed_tmp" ${codexNix}
        fi
        printf '%s\n' "${codexImage}" > ${codexNix}/.ghostship-seeded-image
        chown -R 3000:3000 ${codexNix}
      fi
    '';
  };
}
