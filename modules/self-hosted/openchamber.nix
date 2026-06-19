{
  inputs,
  lib,
  pkgs,
  ...
}:

let
  openchamberHome = "/srv/apps/openchamber/home";
  openchamberDocker = "/srv/apps/openchamber/docker";
  openchamberWorkspace = "/srv/apps/openchamber/workspace";
  openchamberAutomation = "${openchamberHome}/.automation";
  openchamberImageStateMarker = "${openchamberHome}/.local/share/ghostship-openchamber/image-generation";
  imageName = "localhost/ghostship-openchamber";
  imageTag = "openchamber-${inputs.self.shortRev or inputs.self.rev or "dirty"}";

  openchamberPackages = with pkgs; [
    nix
    s6
    docker
    supercronic
    webhook
    go-task
    git
    git-lfs
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
    p7zip
    iptables
    iproute2
    kmod
    su-exec
    which
    file
    bashInteractive
    cacert
  ];

  openchamberPath = lib.makeBinPath openchamberPackages;
  openchamberRuntimeEnv = ''
    export HOME=/home/openchamber
    export USER=openchamber
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export NPM_CONFIG_PREFIX="$HOME/.local/share/openchamber-tools/npm"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export PATH=$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:${openchamberPath}:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export OPENCHAMBER_AUTOMATION_DIR=$HOME/.automation
    export OPENCHAMBER_WEBHOOK_PORT="''${OPENCHAMBER_WEBHOOK_PORT:-9000}"
  '';

  openchamberToolMaintenance = pkgs.writeShellScriptBin "openchamber-tool-maintenance" ''
    set -eu

    ${openchamberRuntimeEnv}
    export NODE_NO_WARNINGS=1

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    log_warn() {
      printf 'warn: %s\n' "$1" >&2
    }

    install_agent_cli() {
      package="$1"
      label="$2"

      log_info "installing or upgrading $label"

      if ! install_output="$(npm install -g --no-fund --no-audit "$package@latest" 2>&1)"; then
        log_warn "$label install failed"
        if [ -n "$install_output" ]; then
          printf '%s\n' "$install_output" >&2
        fi
        return 1
      fi

      if [ -n "$install_output" ]; then
        printf '%s\n' "$install_output" >&2
      fi
    }

    opencode_loader_name() {
      case "$(uname -m)" in
        aarch64|arm64)
          printf '%s\n' "ld-linux-aarch64.so.1"
          ;;
        x86_64|amd64)
          printf '%s\n' "ld-linux-x86-64.so.2"
          ;;
        *)
          return 1
          ;;
      esac
    }

    find_nix_glibc_loader() {
      loader_name="$(opencode_loader_name)" || return 1

      for store_dir in /nix/store "$HOME/.local/share/nix/root/nix/store"; do
        if [ ! -d "$store_dir" ]; then
          continue
        fi

        for candidate in "$store_dir"/*-glibc-*/lib/"$loader_name"; do
          if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
          fi
        done
      done

      return 1
    }

    install_opencode_platform_wrapper() {
      platform_package="$1"
      fallback_bin="$NPM_CONFIG_PREFIX/lib/node_modules/$platform_package/bin/opencode"

      if [ ! -x "$fallback_bin" ]; then
        log_warn "$platform_package binary is missing"
        return 1
      fi

      loader="$(find_nix_glibc_loader || true)"

      rm -f "$NPM_CONFIG_PREFIX/bin/opencode"
      cat > "$NPM_CONFIG_PREFIX/bin/opencode" <<EOF
    #!/usr/bin/env sh
    set -eu
    fallback_bin='$fallback_bin'
    loader='$loader'
    if [ -n "\$loader" ]; then
      exec "\$loader" --library-path "\''${loader%/*}" "\$fallback_bin" "\$@"
    fi
    exec "\$fallback_bin" "\$@"
    EOF
      chmod 0755 "$NPM_CONFIG_PREFIX/bin/opencode"
    }

    install_opencode_cli() {
      log_info "installing or upgrading opencode"

      rm -f "$NPM_CONFIG_PREFIX/bin/opencode"

      if install_output="$(npm install -g --no-fund --no-audit opencode-ai@latest 2>&1)"; then
        if [ -n "$install_output" ]; then
          printf '%s\n' "$install_output" >&2
        fi
        return 0
      fi

      log_warn "opencode install failed, trying platform package"
      if [ -n "$install_output" ]; then
        printf '%s\n' "$install_output" >&2
      fi

      case "$(uname -m)" in
        aarch64|arm64)
          platform_package="opencode-linux-arm64"
          ;;
        x86_64|amd64)
          platform_package="opencode-linux-x64"
          ;;
        *)
          log_warn "unsupported opencode fallback architecture: $(uname -m)"
          return 1
          ;;
      esac

      if ! platform_output="$(npm install -g --no-fund --no-audit "$platform_package@latest" 2>&1)"; then
        log_warn "$platform_package install failed"
        if [ -n "$platform_output" ]; then
          printf '%s\n' "$platform_output" >&2
        fi
        return 1
      fi

      if [ -n "$platform_output" ]; then
        printf '%s\n' "$platform_output" >&2
      fi

      install_opencode_platform_wrapper "$platform_package"
    }

    install_user_shim() {
      name="$1"
      target="$2"

      cat > "$HOME/.local/bin/$name" <<EOF
    #!/usr/bin/env sh
    set -eu
    target='$target'
    if [ ! -x "\$target" ]; then
      printf 'error: %s is not installed yet; run openchamber-tool-maintenance\n' "$name" >&2
      exit 1
    fi
    exec "\$target" "\$@"
    EOF
      chmod 0755 "$HOME/.local/bin/$name"
    }

    mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib"

    install_agent_cli "@openchamber/web" "openchamber"
    install_opencode_cli
    install_user_shim "openchamber" "$NPM_CONFIG_PREFIX/bin/openchamber"
    install_user_shim "opencode" "$NPM_CONFIG_PREFIX/bin/opencode"
  '';

  openchamberContainerSetup = pkgs.writeShellScriptBin "openchamber-container-setup" ''
    set -eu

    ${openchamberRuntimeEnv}

    mkdir -p "$HOME/.local/bin" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$HOME/.config/openchamber" "$HOME/.config/opencode" "$OPENCHAMBER_AUTOMATION_DIR" /workspace /mnt/share /var/lib/docker /var/run /tmp
    chown -R openchamber:openchamber "$HOME" /workspace
    exec su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
  '';

  openchamberDockerdRun = pkgs.writeShellScriptBin "openchamber-svc-dockerd-run" ''
    set -eu

    ${openchamberRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  openchamberWebRun = pkgs.writeShellScriptBin "openchamber-svc-web-run" ''
    set -eu

    ${openchamberRuntimeEnv}
    unset OPENCHAMBER_UI_PASSWORD UI_PASSWORD
    export OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true

    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    chmod 0666 /var/run/docker.sock || true

    cd /home/openchamber

    exec su-exec openchamber:openchamber env \
      HOME="$HOME" \
      USER="$USER" \
      PATH="$PATH" \
      NPM_CONFIG_PREFIX="$NPM_CONFIG_PREFIX" \
      npm_config_prefix="$NPM_CONFIG_PREFIX" \
      DOCKER_HOST="$DOCKER_HOST" \
      NIX_SSL_CERT_FILE="$NIX_SSL_CERT_FILE" \
      SSL_CERT_FILE="$SSL_CERT_FILE" \
      NIX_CONFIG="$NIX_CONFIG" \
      openchamber serve --host 0.0.0.0 --port 3000 --foreground
  '';

  openchamberSupercronicRun = pkgs.writeShellScriptBin "openchamber-svc-supercronic-run" ''
    set -eu

    ${openchamberRuntimeEnv}

    exec su-exec openchamber:openchamber env \
      HOME="$HOME" \
      USER="$USER" \
      PATH="$PATH" \
      DOCKER_HOST="$DOCKER_HOST" \
      NIX_SSL_CERT_FILE="$NIX_SSL_CERT_FILE" \
      SSL_CERT_FILE="$SSL_CERT_FILE" \
      NIX_CONFIG="$NIX_CONFIG" \
      OPENCHAMBER_AUTOMATION_DIR="$OPENCHAMBER_AUTOMATION_DIR" \
      supercronic -no-reap -inotify -passthrough-logs "$OPENCHAMBER_AUTOMATION_DIR/crontab"
  '';

  openchamberWebhookRun = pkgs.writeShellScriptBin "openchamber-svc-webhook-run" ''
    set -eu

    ${openchamberRuntimeEnv}

    cd "$OPENCHAMBER_AUTOMATION_DIR"

    exec su-exec openchamber:openchamber env \
      HOME="$HOME" \
      USER="$USER" \
      PATH="$PATH" \
      DOCKER_HOST="$DOCKER_HOST" \
      NIX_SSL_CERT_FILE="$NIX_SSL_CERT_FILE" \
      SSL_CERT_FILE="$SSL_CERT_FILE" \
      NIX_CONFIG="$NIX_CONFIG" \
      OPENCHAMBER_AUTOMATION_DIR="$OPENCHAMBER_AUTOMATION_DIR" \
      webhook \
        -hooks "$OPENCHAMBER_AUTOMATION_DIR/hooks.json" \
        -hotreload \
        -ip 0.0.0.0 \
        -port "$OPENCHAMBER_WEBHOOK_PORT" \
        -verbose
  '';

  openchamberEntrypoint = pkgs.writeShellScriptBin "openchamber-s6-entrypoint" ''
    set -eu

    ${openchamberRuntimeEnv}
    ${openchamberContainerSetup}/bin/openchamber-container-setup

    exec s6-svscan /etc/s6/services
  '';

  openchamberImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = openchamberPackages ++ [
      openchamberEntrypoint
      openchamberContainerSetup
      openchamberDockerdRun
      openchamberWebRun
      openchamberSupercronicRun
      openchamberWebhookRun
      openchamberToolMaintenance
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.dockerTools.caCertificates
    ];
    extraCommands = ''
      mkdir -p etc/nix etc/s6/services nix/store nix/var/log/nix nix/var/nix tmp workspace home/openchamber
      mkdir -p mnt/share var/lib/docker var/run
      for service in dockerd openchamber-web supercronic webhook; do
        mkdir -p "etc/s6/services/$service"
      done
      ln -s ${openchamberDockerdRun}/bin/openchamber-svc-dockerd-run etc/s6/services/dockerd/run
      ln -s ${openchamberWebRun}/bin/openchamber-svc-web-run etc/s6/services/openchamber-web/run
      ln -s ${openchamberSupercronicRun}/bin/openchamber-svc-supercronic-run etc/s6/services/supercronic/run
      ln -s ${openchamberWebhookRun}/bin/openchamber-svc-webhook-run etc/s6/services/webhook/run
      chmod 1777 tmp
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      openchamber:x:3000:3000:OpenChamber:/home/openchamber:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      openchamber:x:3000:
      EOF
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      EOF
    '';
    fakeRootCommands = ''
      chown -R 3000:3000 nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
    '';
    config = {
      Cmd = [ "${openchamberEntrypoint}/bin/openchamber-s6-entrypoint" ];
      Env = [
        "HOME=/home/openchamber"
        "USER=openchamber"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_CONFIG_HOME=/home/openchamber/.config"
        "XDG_STATE_HOME=/home/openchamber/.local/state"
        "XDG_CACHE_HOME=/home/openchamber/.cache"
        "XDG_DATA_HOME=/home/openchamber/.local/share"
        "NPM_CONFIG_PREFIX=/home/openchamber/.local/share/openchamber-tools/npm"
        "npm_config_prefix=/home/openchamber/.local/share/openchamber-tools/npm"
        "PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "OPENCHAMBER_AUTOMATION_DIR=/home/openchamber/.automation"
        "OPENCHAMBER_WEBHOOK_PORT=9000"
        "OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true"
      ];
      WorkingDir = "/home/openchamber";
      ExposedPorts = {
        "3000/tcp" = { };
        "9000/tcp" = { };
      };
    };
  };

in
{
  virtualisation.oci-containers.containers."openchamber" = {
    image = "${imageName}:${imageTag}";
    imageFile = openchamberImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--network=ghostship_net"
      "--health-cmd=curl -fsS http://127.0.0.1:3000/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=2m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${openchamberDocker}:/var/lib/docker:rw"
      "${openchamberWorkspace}:/workspace:rw"
      "${openchamberHome}:/home/openchamber:rw"
      "/mnt/share:/mnt/share:rw"
    ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/openchamber 0755 root root -"
    "d ${openchamberDocker} 0755 root root -"
    "d ${openchamberHome} 0755 3000 3000 -"
    "d ${openchamberWorkspace} 0755 3000 3000 -"
    "d ${openchamberAutomation} 0755 3000 3000 -"
    "d ${openchamberAutomation}/tasks 0755 3000 3000 -"
  ];

  systemd.services.podman-openchamber = {
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/openchamber
      install -d -m0755 -o root -g root ${openchamberDocker}
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}
      install -d -m0755 -o 3000 -g 3000 ${openchamberWorkspace}
      install -d -m0755 -o 3000 -g 3000 ${openchamberAutomation}
      install -d -m0755 -o 3000 -g 3000 ${openchamberAutomation}/tasks
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/openchamber
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/opencode

      if [ ! -e ${openchamberAutomation}/crontab ]; then
        cat > ${openchamberAutomation}/crontab <<'EOF'
      # Supercronic crontab for the OpenChamber container.
      # Run Taskfile jobs from this persistent automation directory, for example:
      # */15 * * * * cd /home/openchamber/.automation && task -t Taskfile.yml cron:default
      EOF
        chown 3000:3000 ${openchamberAutomation}/crontab
        chmod 0644 ${openchamberAutomation}/crontab
      fi

      if [ ! -e ${openchamberAutomation}/hooks.json ]; then
        cat > ${openchamberAutomation}/hooks.json <<'EOF'
      []
      EOF
        chown 3000:3000 ${openchamberAutomation}/hooks.json
        chmod 0644 ${openchamberAutomation}/hooks.json
      fi

      if [ ! -e ${openchamberAutomation}/Taskfile.yml ]; then
        cat > ${openchamberAutomation}/Taskfile.yml <<'EOF'
      version: '3'

      tasks:
        cron:default:
          desc: Placeholder cron task for OpenChamber container automation.
          cmds:
            - echo "Define cron automation in /home/openchamber/.automation/Taskfile.yml"

        webhook:default:
          desc: Placeholder webhook task for OpenChamber container automation.
          cmds:
            - echo "Define webhook automation in /home/openchamber/.automation/Taskfile.yml"
      EOF
        chown 3000:3000 ${openchamberAutomation}/Taskfile.yml
        chmod 0644 ${openchamberAutomation}/Taskfile.yml
      fi

      current_image_state=""
      if [ -e ${openchamberImageStateMarker} ]; then
        current_image_state="$(cat ${openchamberImageStateMarker})"
      fi

      if [ "$current_image_state" != "${openchamberImage}" ]; then
        rm -rf \
          ${openchamberHome}/.cache/nix \
          ${openchamberHome}/.local/share/nix \
          ${openchamberHome}/.local/state/nix \
          ${openchamberHome}/.nix-profile

        install -d -m0755 -o 3000 -g 3000 "$(dirname ${openchamberImageStateMarker})"
        printf '%s\n' "${openchamberImage}" > ${openchamberImageStateMarker}
        chown 3000:3000 ${openchamberImageStateMarker}
      fi
    '';
  };
}
