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
  imageName = "localhost/ghostship-openchamber";
  imageTag = "openchamber-${inputs.self.shortRev or inputs.self.rev or "dirty"}";

  openchamberPackages = with pkgs; [
    nix
    systemd
    docker
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
    hm_session_vars="$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      . "$hm_session_vars"
    fi
    export PATH=$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:${openchamberPath}:/bin:/usr/bin:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export XDG_RUNTIME_DIR=/run/user/3000
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
  '';

  sourceHmSessionVarsIfPresent = ''
    hm_session_vars="\$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "\$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      . "\$hm_session_vars"
    fi
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
    ${sourceHmSessionVarsIfPresent}
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

    install_opencode_user_shim() {
      target="$1"

      cat > "$HOME/.local/bin/opencode" <<EOF
    #!/usr/bin/env sh
    set -eu
    ${sourceHmSessionVarsIfPresent}
    target='$target'
    if [ ! -x "\$target" ]; then
      printf 'error: opencode is not installed yet; run openchamber-tool-maintenance\n' >&2
      exit 1
    fi
    exec "\$target" "\$@"
    EOF
      chmod 0755 "$HOME/.local/bin/opencode"
    }

    mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib"

    install_agent_cli "@openchamber/web" "openchamber"
    install_opencode_cli
    install_user_shim "openchamber" "$NPM_CONFIG_PREFIX/bin/openchamber"
    install_opencode_user_shim "$NPM_CONFIG_PREFIX/bin/opencode"
  '';

  openchamberToolAutoUpdate = pkgs.writeShellScriptBin "openchamber-tool-auto-update" ''
    set -eu

    ${openchamberRuntimeEnv}
    export NODE_NO_WARNINGS=1

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    user_version() {
      tool="$1"
      su-exec openchamber:openchamber sh -c '
        tool="$1"
        if ! command -v "$tool" >/dev/null 2>&1; then
          exit 0
        fi
        "$tool" --version 2>/dev/null | sed -n "1p" || true
      ' sh "$tool"
    }

    before_openchamber="$(user_version openchamber)"
    before_opencode="$(user_version opencode)"

    su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance

    after_openchamber="$(user_version openchamber)"
    after_opencode="$(user_version opencode)"

    log_info "openchamber: ''${before_openchamber:-missing} -> ''${after_openchamber:-missing}"
    log_info "opencode: ''${before_opencode:-missing} -> ''${after_opencode:-missing}"

    if [ "$before_openchamber" != "$after_openchamber" ] || [ "$before_opencode" != "$after_opencode" ]; then
      if systemctl is-active --quiet openchamber-web.service; then
        log_info "restarting openchamber-web.service after tool update"
        systemctl restart openchamber-web.service
      else
        log_info "openchamber-web.service is not active; leaving it stopped"
      fi
    else
      log_info "installed tool versions are unchanged"
    fi
  '';

  openchamberWebMonitor = pkgs.writeShellScriptBin "openchamber-web-monitor" ''
    set -eu

    ${openchamberRuntimeEnv}

    log_file="$HOME/.config/openchamber/logs/openchamber-web-monitor.log"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    unhealthy_reason=""

    if ! systemctl is-active --quiet openchamber-web.service; then
      unhealthy_reason="openchamber-web.service is not active"
    elif ! curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null; then
      unhealthy_reason="OpenChamber root endpoint is not responding"
    fi

    if [ -z "$unhealthy_reason" ]; then
      found_opencode=0
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q 'opencode serve'; then
          found_opencode=1
          break
        fi
      done

      if [ "$found_opencode" -ne 1 ]; then
        unhealthy_reason="managed OpenCode server process is missing"
      fi
    fi

    if [ -z "$unhealthy_reason" ]; then
      log_info "healthy"
      exit 0
    fi

    log_info "unhealthy: $unhealthy_reason; restarting openchamber-web.service"
    systemctl reset-failed openchamber-web.service || true
    systemctl restart openchamber-web.service
  '';

  openchamberWebRun = pkgs.writeShellScriptBin "openchamber-web-run" ''
    set -eu

    ${openchamberRuntimeEnv}
    export XDG_RUNTIME_DIR=/run/user/3000
    unset OPENCHAMBER_UI_PASSWORD UI_PASSWORD
    export OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true

    for _ in $(seq 1 30); do
      if docker info >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    cd /home/openchamber
    rm -f \
      "$HOME/.config/openchamber/run/openchamber-3000.json" \
      "$HOME/.config/openchamber/run/openchamber-3000.pid"

    exec openchamber serve --host 0.0.0.0 --port 3000 --foreground
  '';

  openchamberContainerSetup = pkgs.writeShellScriptBin "openchamber-container-setup" ''
    set -eu

    ${openchamberRuntimeEnv}

    mkdir -p "$HOME/.local/bin" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$HOME/.config/openchamber" "$HOME/.config/opencode" /workspace /mnt/share /var/lib/docker /var/run /tmp /run/user/3000
    chown openchamber:openchamber /run/user/3000
    chmod 0700 /run/user/3000
    rm -rf \
      "$HOME/.codex" \
      "$HOME/.gemini" \
      "$HOME/.local/state/codex" \
      "$HOME/.local/bin/codex" \
      "$HOME/.local/bin/gemini" \
      "$HOME/.local/bin/gemini-cli"
    su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
    cat > "$HOME/.local/bin/openchamber-web-run" <<'EOF'
    #!/bin/sh
    exec ${openchamberWebRun}/bin/openchamber-web-run "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-web-run"
    chmod 0755 "$HOME/.local/bin/openchamber-web-run"

  '';

  openchamberDockerdRun = pkgs.writeShellScriptBin "openchamber-dockerd-run" ''
    set -eu

    ${openchamberRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --group=openchamber \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  openchamberEntrypoint = pkgs.writeShellScriptBin "openchamber-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  openchamberImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = openchamberPackages ++ [
      openchamberEntrypoint
      openchamberContainerSetup
      openchamberDockerdRun
      openchamberWebRun
      openchamberToolMaintenance
      openchamberToolAutoUpdate
      openchamberWebMonitor
      pkgs.dockerTools.binSh
      pkgs.dockerTools.usrBinEnv
      pkgs.dockerTools.caCertificates
    ];
    extraCommands = ''
      mkdir -p etc/nix etc/systemd/system/multi-user.target.wants nix/store nix/var/log/nix nix/var/nix tmp workspace home/openchamber
      mkdir -p mnt/share run/user var/lib/docker var/log/journal var/run
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
      cat > etc/systemd/system/openchamber-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare OpenChamber container state
      DefaultDependencies=no

      [Service]
      Type=oneshot
      ExecStart=${openchamberContainerSetup}/bin/openchamber-container-setup
      RemainAfterExit=yes
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/dockerd.service <<'EOF'
      [Unit]
      Description=OpenChamber Docker daemon
      DefaultDependencies=no
      After=openchamber-container-setup.service
      Requires=openchamber-container-setup.service

      [Service]
      Type=simple
      ExecStart=${openchamberDockerdRun}/bin/openchamber-dockerd-run
      Restart=always
      RestartSec=5
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-user-manager.service <<'EOF'
      [Unit]
      Description=OpenChamber user systemd manager
      DefaultDependencies=no
      ConditionPathExists=/home/openchamber/.config/systemd/user/default.target
      After=openchamber-container-setup.service dockerd.service
      Requires=openchamber-container-setup.service dockerd.service

      [Service]
      Type=simple
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      ExecStart=${pkgs.systemd}/lib/systemd/systemd --user
      Restart=always
      RestartSec=5
      KillMode=mixed
      Delegate=yes
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-web.service <<'EOF'
      [Unit]
      Description=OpenChamber Web
      DefaultDependencies=no
      After=openchamber-container-setup.service dockerd.service
      Requires=openchamber-container-setup.service dockerd.service

      [Service]
      Type=simple
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberWebRun}/bin/openchamber-web-run
      Restart=always
      RestartSec=5
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update OpenChamber and OpenCode tools
      DefaultDependencies=no
      After=openchamber-container-setup.service dockerd.service
      Requires=openchamber-container-setup.service dockerd.service

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberToolAutoUpdate}/bin/openchamber-tool-auto-update
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-auto-update.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-auto-update.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic OpenChamber and OpenCode tool updates
      DefaultDependencies=no
      After=openchamber-container-setup.service

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=openchamber-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-web-monitor.service <<'EOF'
      [Unit]
      Description=Monitor OpenChamber web and managed OpenCode
      DefaultDependencies=no
      After=openchamber-web.service
      Wants=openchamber-web.service

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberWebMonitor}/bin/openchamber-web-monitor
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-web-monitor.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-web-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-web-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic OpenChamber web monitor
      DefaultDependencies=no
      After=openchamber-web.service

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-web-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=OpenChamber Multi-User System
      DefaultDependencies=no
      Wants=openchamber-container-setup.service dockerd.service openchamber-user-manager.service openchamber-web.service openchamber-tool-auto-update.timer openchamber-web-monitor.timer
      After=openchamber-container-setup.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../openchamber-container-setup.service etc/systemd/system/multi-user.target.wants/openchamber-container-setup.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../openchamber-user-manager.service etc/systemd/system/multi-user.target.wants/openchamber-user-manager.service
      ln -s ../openchamber-web.service etc/systemd/system/multi-user.target.wants/openchamber-web.service
      ln -s ../openchamber-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/openchamber-tool-auto-update.timer
      ln -s ../openchamber-web-monitor.timer etc/systemd/system/multi-user.target.wants/openchamber-web-monitor.timer
      '';
    fakeRootCommands = ''
      chown -R 3000:3000 nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
    '';
    config = {
      Cmd = [ "${openchamberEntrypoint}/bin/openchamber-systemd-entrypoint" ];
      Env = [
        "HOME=/home/openchamber"
        "USER=openchamber"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "XDG_CONFIG_HOME=/home/openchamber/.config"
        "XDG_STATE_HOME=/home/openchamber/.local/state"
        "XDG_CACHE_HOME=/home/openchamber/.cache"
        "XDG_DATA_HOME=/home/openchamber/.local/share"
        "NPM_CONFIG_PREFIX=/home/openchamber/.local/share/openchamber-tools/npm"
        "npm_config_prefix=/home/openchamber/.local/share/openchamber-tools/npm"
        "PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true"
      ];
      WorkingDir = "/home/openchamber";
      ExposedPorts = {
        "3000/tcp" = { };
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
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=60"
      "--network=ghostship_net"
      "--health-cmd=curl -fsS http://127.0.0.1:3000/ >/dev/null || exit 1"
      "--health-interval=30s"
      "--health-timeout=10s"
      "--health-retries=5"
      "--health-start-period=5m"
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
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/openchamber
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/opencode

      if [ -e ${openchamberHome}/.config/systemd/user/openchamber.service ] \
        && grep -q 'ExecStart=/home/openchamber/.local/bin/openchamber-web-run' ${openchamberHome}/.config/systemd/user/openchamber.service; then
        rm -f ${openchamberHome}/.config/systemd/user/openchamber.service
      fi
      if [ -e ${openchamberHome}/.config/systemd/user/default.target ] \
        && grep -q 'OpenChamber User Default Target' ${openchamberHome}/.config/systemd/user/default.target; then
        rm -f ${openchamberHome}/.config/systemd/user/default.target
      fi
      rm -f ${openchamberHome}/.config/systemd/user/default.target.wants/openchamber.service
      if [ -d ${openchamberHome}/.config/systemd/user ]; then
        for unit in \
          ghostship-agent-repair-install.service \
          ghostship-agent-repair-install.timer \
          ghostship-am-collect-browser.service \
          ghostship-am-collect-browser.timer \
          ghostship-am-collect-craigslist.service \
          ghostship-am-collect-craigslist.timer \
          ghostship-am-collect-public.service \
          ghostship-am-collect-public.timer \
          ghostship-am-generate.service \
          ghostship-am-generate.timer \
          ghostship-am-maintain-gmail-auth.service \
          ghostship-am-maintain-gmail-auth.timer; do
          rm -f \
            ${openchamberHome}/.config/systemd/user/"$unit" \
            ${openchamberHome}/.config/systemd/user/default.target.wants/"$unit"
        done
        find ${openchamberHome}/.config/systemd/user -type l \
          -lname '/nix/store/*home-manager-files/.config/systemd/user/*' \
          -delete
      fi
    '';
  };
}
