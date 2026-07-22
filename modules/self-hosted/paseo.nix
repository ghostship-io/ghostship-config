{
  config,
  inputs,
  lib,
  pkgs,
  ...
}:

let
  paseoHome = "/srv/apps/paseo/home";
  paseoDocker = "/srv/apps/paseo/docker";
  paseoNixRoot = "/srv/apps/paseo/nix-root";
  paseoWorkspace = "/srv/apps/paseo/workspace";
  paseoSecrets = config.ghostship.selfHostedSecrets.projections.paseo.path;
  paseoSecretsFile = "/run/secrets/paseo.env";
  imageName = "localhost/ghostship-paseo";
  imageTag = "paseo-${inputs.self.shortRev or inputs.self.rev or "dirty"}";

  paseoPackages = with pkgs; [
    nix
    systemd
    dbus
    pam
    gnome-keyring
    libsecret
    docker
    cloudflared
    sudo
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
    lbzip2
    unzip
    p7zip
    procps
    iptables
    iproute2
    kmod
    su-exec
    which
    file
    bashInteractive
    cacert
  ];

  paseoPath = lib.makeBinPath paseoPackages;
  paseoRuntimeEnv = ''
    if [ -f ${paseoSecretsFile} ]; then
      set -a
      # shellcheck disable=SC1091
      . ${paseoSecretsFile}
      set +a
    fi
    export HOME=/home/paseo
    export USER=paseo
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export NPM_CONFIG_PREFIX="$HOME/.local/share/paseo-tools/npm"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export OPENCODE_AUTOMATION_DIR="$HOME/.automation"
    export PASEO_HOME="$HOME/.paseo"
    export PASEO_LISTEN="0.0.0.0:6767"
    export PASEO_WEB_UI_ENABLED=true
    export AGY_CLI_DISABLE_AUTO_UPDATE=true
    hm_session_vars="$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "$hm_session_vars"
      if [ "$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
    export PATH=$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:${paseoPath}:/bin:/usr/bin:$PATH
    export DOCKER_HOST=unix:///var/run/docker.sock
    export XDG_RUNTIME_DIR=/run/user/3000
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
    export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
    export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
    export NIX_CONFIG="experimental-features = nix-command flakes"
    export NIX_REMOTE=daemon
  '';

  sourceHmSessionVarsIfPresent = ''
    hm_session_vars="\$HOME/.nix-profile/etc/profile.d/hm-session-vars.sh"
    if [ -f "\$hm_session_vars" ]; then
      # shellcheck disable=SC1090
      case "\$-" in *u*) restore_nounset=1 ;; *) restore_nounset=0 ;; esac
      set +u
      . "\$hm_session_vars"
      if [ "\$restore_nounset" -eq 1 ]; then
        set -u
      fi
    fi
  '';

  paseoIdleCheck = ''
    is_paseo_idle() {
      if ! activity="$(PASEO_HOST=127.0.0.1:6767 paseo ls --global --json 2>/dev/null)"; then
        return 1
      fi

      printf '%s\n' "$activity" | ${pkgs.jq}/bin/jq -e '
        if type != "array" then
          false
        else
          all(.[]; type == "object" and (.status != "initializing" and .status != "running"))
        end
      ' >/dev/null 2>&1
    }
  '';

  paseoProviderCheck = ''
    paseo_providers_healthy() {
      if ! providers="$(PASEO_HOST=127.0.0.1:6767 paseo provider ls --json 2>/dev/null)"; then
        return 1
      fi
      printf '%s\n' "$providers" | ${pkgs.jq}/bin/jq -e '
        def ready($name):
          any(.[]; .provider == $name and .status == "available" and .enabled == "Enabled");
        type == "array" and ready("codex") and ready("opencode")
      ' >/dev/null 2>&1
    }
  '';

  paseoToolMaintenance = pkgs.writeShellScriptBin "paseo-tool-maintenance" ''
    set -eu

    ${paseoRuntimeEnv}
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
      printf 'error: %s is not installed yet; run paseo-tool-maintenance\n' "$name" >&2
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
      printf 'error: opencode is not installed yet; run paseo-tool-maintenance\n' >&2
      exit 1
    fi
    exec "\$target" "\$@"
    EOF
      chmod 0755 "$HOME/.local/bin/opencode"
    }

    install_antigravity_cli() {
      staging_dir="$(mktemp -d "$XDG_CACHE_HOME/antigravity-install.XXXXXX")"
      trap 'rm -rf "$staging_dir"' EXIT HUP INT TERM
      mkdir -p "$staging_dir/home" "$staging_dir/config"
      antigravity_dir="$XDG_DATA_HOME/paseo-tools/antigravity"

      log_info "installing or upgrading Antigravity CLI"
      if ! ${pkgs.curl}/bin/curl -fsSL https://antigravity.google/cli/install.sh \
        | HOME="$staging_dir/home" XDG_CONFIG_HOME="$staging_dir/config" \
          ${pkgs.bash}/bin/bash -s -- --dir "$staging_dir"; then
        log_warn "Antigravity CLI install failed"
        return 1
      fi
      if [ ! -x "$staging_dir/agy" ]; then
        log_warn "Antigravity installer did not produce agy"
        return 1
      fi
      loader="$(find_nix_glibc_loader || true)"
      if [ -z "$loader" ]; then
        log_warn "Nix glibc loader is unavailable for Antigravity CLI"
        return 1
      fi
      mkdir -p "$antigravity_dir"
      install -m 0755 "$staging_dir/agy" "$antigravity_dir/agy.new"
      mv "$antigravity_dir/agy.new" "$antigravity_dir/agy"
      cat > "$HOME/.local/bin/agy" <<EOF
    #!/usr/bin/env sh
    set -eu
    exec '$loader' --library-path "''${loader%/*}" '$antigravity_dir/agy' "\$@"
    EOF
      chmod 0755 "$HOME/.local/bin/agy"
      rm -rf "$staging_dir"
      trap - EXIT HUP INT TERM
    }

    mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$NPM_CONFIG_PREFIX/bin" "$NPM_CONFIG_PREFIX/lib"

    install_agent_cli "@getpaseo/cli" "paseo"
    install_agent_cli "@openai/codex" "codex"
    install_opencode_cli
    install_antigravity_cli
    install_user_shim "paseo" "$NPM_CONFIG_PREFIX/bin/paseo"
    install_user_shim "codex" "$NPM_CONFIG_PREFIX/bin/codex"
    install_opencode_user_shim "$NPM_CONFIG_PREFIX/bin/opencode"
  '';

  paseoToolAutoUpdate = pkgs.writeShellScriptBin "paseo-tool-auto-update" ''
    set -eu

    ${paseoRuntimeEnv}
    export NODE_NO_WARNINGS=1

    state_dir="/run/paseo-tool-update"
    pending_restart="$state_dir/restart.pending"
    install -d -m 0700 "$state_dir"

    exec 9>"$state_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    ${paseoIdleCheck}

    if systemctl is-active --quiet paseo-daemon.service && ! is_paseo_idle; then
      log_info "Paseo reports active or unknown work; tool update deferred"
      exit 0
    fi

    user_version() {
      tool="$1"
      su-exec paseo:paseo sh -c '
        tool="$1"
        if ! command -v "$tool" >/dev/null 2>&1; then
          exit 0
        fi
        "$tool" --version 2>/dev/null | sed -n "1p" || true
      ' sh "$tool"
    }

    before_paseo="$(user_version paseo)"
    before_codex="$(user_version codex)"
    before_opencode="$(user_version opencode)"
    before_agy="$(user_version agy)"

    su-exec paseo:paseo ${paseoToolMaintenance}/bin/paseo-tool-maintenance

    after_paseo="$(user_version paseo)"
    after_codex="$(user_version codex)"
    after_opencode="$(user_version opencode)"
    after_agy="$(user_version agy)"

    log_info "paseo: ''${before_paseo:-missing} -> ''${after_paseo:-missing}"
    log_info "codex: ''${before_codex:-missing} -> ''${after_codex:-missing}"
    log_info "opencode: ''${before_opencode:-missing} -> ''${after_opencode:-missing}"
    log_info "agy: ''${before_agy:-missing} -> ''${after_agy:-missing}"

    if [ "$before_paseo" != "$after_paseo" ] \
      || [ "$before_codex" != "$after_codex" ] \
      || [ "$before_opencode" != "$after_opencode" ] \
      || [ "$before_agy" != "$after_agy" ]; then
      pending_tmp="$pending_restart.tmp"
      {
        printf 'paseo=%s\n' "$after_paseo"
        printf 'codex=%s\n' "$after_codex"
        printf 'opencode=%s\n' "$after_opencode"
        printf 'agy=%s\n' "$after_agy"
      } > "$pending_tmp"
      mv "$pending_tmp" "$pending_restart"
      log_info "tool update downloaded; queued restart until Paseo is idle"
    else
      log_info "installed tool versions are unchanged"
    fi
  '';

  paseoToolUpdateRestart = pkgs.writeShellScriptBin "paseo-tool-update-restart" ''
    set -eu

    ${paseoRuntimeEnv}

    state_dir="/run/paseo-tool-update"
    pending_restart="$state_dir/restart.pending"

    log_info() {
      printf 'info: %s\n' "$1" >&2
    }

    ${paseoIdleCheck}

    [ -f "$pending_restart" ] || exit 0

    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "tool maintenance is still running; leaving restart queued"
      exit 0
    fi

    if ! systemctl is-active --quiet paseo-daemon.service; then
      log_info "paseo-daemon.service is stopped; clearing queued restart"
      rm -f "$pending_restart"
      exit 0
    fi

    if ! is_paseo_idle; then
      log_info "Paseo reports active or unknown work; leaving restart queued"
      exit 0
    fi

    sleep 5

    if [ ! -f "$pending_restart" ]; then
      log_info "queued restart was already applied by another service start"
      exit 0
    fi

    if ! is_paseo_idle; then
      log_info "Paseo is no longer idle; leaving restart queued"
      exit 0
    fi

    log_info "Paseo reports all work complete; applying queued maintenance restart"
    systemctl restart paseo-daemon.service
    rm -f "$pending_restart"
  '';

  paseoQueueBootstrapRestart = pkgs.writeShellScriptBin "paseo-queue-bootstrap-restart" ''
    set -eu

    state_dir="/run/paseo-tool-update"
    pending_restart="$state_dir/restart.pending"
    ${pkgs.coreutils}/bin/install -d -m 0700 "$state_dir"

    exec 9>"$state_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    pending_tmp="$pending_restart.tmp"
    printf 'source=bootstrap\n' > "$pending_tmp"
    ${pkgs.coreutils}/bin/mv "$pending_tmp" "$pending_restart"
  '';

  paseoDaemonMonitor = pkgs.writeShellScriptBin "paseo-daemon-monitor" ''
    set -eu

    ${paseoRuntimeEnv}

    log_file="$HOME/.paseo-container/logs/paseo-daemon-monitor.log"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    ${paseoIdleCheck}
    ${paseoProviderCheck}

    unhealthy_reason=""
    web_was_active=1

    if ! systemctl is-active --quiet paseo-daemon.service; then
      unhealthy_reason="paseo-daemon.service is not active"
      web_was_active=0
    elif ! curl -fsS --max-time 5 http://127.0.0.1:6767/api/health >/dev/null; then
      unhealthy_reason="Paseo health endpoint is not responding"
    elif ! paseo_providers_healthy; then
      unhealthy_reason="Codex or OpenCode provider is unavailable"
    elif ! command -v agy >/dev/null 2>&1 || ! agy --version >/dev/null 2>&1; then
      unhealthy_reason="Antigravity CLI is unavailable"
    fi

    if [ -z "$unhealthy_reason" ]; then
      log_info "healthy"
      exit 0
    fi

    if [ "$web_was_active" -eq 1 ] && ! is_paseo_idle; then
      log_info "unhealthy: $unhealthy_reason; Paseo activity is active or unknown; restart deferred"
      exit 0
    fi

    state_dir="/run/paseo-tool-update"
    install -d -m 0700 "$state_dir"
    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "unhealthy: $unhealthy_reason; tool maintenance or restart is in progress; restart deferred"
      exit 0
    fi

    log_info "unhealthy: $unhealthy_reason; restarting paseo-daemon.service"
    systemctl reset-failed paseo-daemon.service || true
    systemctl restart paseo-daemon.service
  '';

  paseoContainerHealth = pkgs.writeShellScriptBin "paseo-container-health" ''
    set -eu

    ${paseoIdleCheck}

    read -r uptime _ < /proc/uptime
    uptime_seconds="''${uptime%%.*}"
    if ! manager_started_usec="$(${pkgs.systemd}/bin/systemctl show -p UserspaceTimestampMonotonic --value)"; then
      exit 0
    fi
    case "$manager_started_usec" in
      ""|*[!0-9]*)
        container_age_seconds=1200
        ;;
      *)
        container_age_seconds=$((uptime_seconds - (manager_started_usec / 1000000)))
        if [ "$container_age_seconds" -lt 0 ]; then
          container_age_seconds=1200
        fi
        ;;
    esac
    if ! setup_state="$(${pkgs.systemd}/bin/systemctl show paseo-container-setup.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! bootstrap_state="$(${pkgs.systemd}/bin/systemctl show paseo-bootstrap.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! web_state="$(${pkgs.systemd}/bin/systemctl show paseo-daemon.service -p ActiveState --value)"; then
      exit 0
    fi

    if [ "$container_age_seconds" -lt 1200 ] \
      && { [ "$setup_state" = "activating" ] \
        || [ "$bootstrap_state" = "activating" ] \
        || [ "$web_state" = "activating" ]; }; then
      exit 0
    fi

    if ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:6767/api/health >/dev/null; then
      exit 0
    fi

    if ! ${pkgs.systemd}/bin/systemctl is-active --quiet paseo-daemon.service; then
      exit 1
    fi

    if is_paseo_idle; then
      exit 1
    fi

    printf 'warning: Paseo health is degraded but activity is active or unknown; container kill deferred\n' >&2
    exit 0
  '';

  paseoApplyConfig = pkgs.writeShellScriptBin "paseo-apply-config" ''
    set -eu

    ${paseoRuntimeEnv}

    recovery_dir="$HOME/.paseo-container/recovery"
    last_good="$recovery_dir/last-good"
    log_file="$HOME/.paseo-container/logs/paseo-apply-config.log"
    systemctl_bin="${pkgs.systemd}/bin/systemctl"
    sudo_bin="/usr/bin/sudo"

    mkdir -p "$recovery_dir" "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    log_error() {
      printf '%s error: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" | tee -a "$log_file" >&2
    }

    restore_config() {
      src="$1"
      if [ ! -d "$src" ]; then
        log_error "no last-good config snapshot exists at $src"
        return 1
      fi

      rm -f \
        "$HOME/.paseo/config.json" \
        "$HOME/.codex/config.toml" \
        "$HOME/.config/opencode/opencode.json" \
        "$HOME/.gemini/antigravity-cli/settings.json"
      if [ -d "$src/home" ]; then
        tar -C "$src/home" -cf - . | tar -C "$HOME" -xf -
      fi
    }

    validate_config() {
      command -v paseo >/dev/null 2>&1 || {
        log_error "paseo CLI is not installed"
        return 1
      }
      command -v codex >/dev/null 2>&1 || {
        log_error "codex CLI is not installed"
        return 1
      }
      command -v opencode >/dev/null 2>&1 || {
        log_error "opencode CLI is not installed"
        return 1
      }
      command -v agy >/dev/null 2>&1 || {
        log_error "Antigravity CLI is not installed"
        return 1
      }

      for file in \
        "$HOME/.paseo/config.json" \
        "$HOME/.config/opencode/opencode.json" \
        "$HOME/.gemini/antigravity-cli/settings.json"; do
        if [ -f "$file" ] && ! jq -e . "$file" >/dev/null; then
          log_error "invalid JSON: $file"
          return 1
        fi
      done
      if [ -f "$HOME/.codex/config.toml" ] \
        && ! ${pkgs.python3}/bin/python - "$HOME/.codex/config.toml" <<'PY'
    import pathlib
    import sys
    import tomllib

    with pathlib.Path(sys.argv[1]).open("rb") as handle:
        tomllib.load(handle)
    PY
      then
        log_error "invalid TOML: $HOME/.codex/config.toml"
        return 1
      fi

      paseo --version >/dev/null
      codex --version >/dev/null
      opencode debug config >/dev/null
      agy --version >/dev/null
    }

    restart_daemon() {
      "$sudo_bin" -n "$systemctl_bin" reset-failed paseo-daemon.service
      "$sudo_bin" -n "$systemctl_bin" restart paseo-daemon.service
    }

    ${paseoProviderCheck}

    wait_healthy() {
      for _ in $(seq 1 90); do
        if curl -fsS --max-time 5 http://127.0.0.1:6767/api/health >/dev/null \
          && paseo_providers_healthy; then
          return 0
        fi
        sleep 1
      done
      return 1
    }

    apply_config() {
      log_info "validating Paseo, Codex, OpenCode, and Antigravity config"
      validate_config

      if [ ! -d "$last_good" ]; then
        log_error "no last-good config snapshot exists; wait for paseo-daemon.service to start successfully once"
        exit 1
      fi

      log_info "restarting paseo-daemon.service"
      restart_daemon

      if wait_healthy; then
        log_info "Paseo providers are healthy"
        exit 0
      fi

      log_error "Paseo providers did not become healthy; restoring last-good config"
      restore_config "$last_good"
      validate_config
      restart_daemon

      if wait_healthy; then
        log_info "rollback restored a healthy Paseo runtime"
        exit 1
      fi

      log_error "rollback did not restore a healthy Paseo runtime"
      exit 1
    }

    case "''${1:-apply}" in
      apply) apply_config ;;
      *)
        printf 'usage: paseo-apply-config [apply]\n' >&2
        exit 2
        ;;
    esac
  '';

  paseoUserUnits = pkgs.writeShellScriptBin "paseo-user-units" ''
    set -eu

    ${paseoRuntimeEnv}

    usage() {
      cat >&2 <<EOF
    usage:
      paseo-user-units reload
      paseo-user-units enable-now <unit>...
      paseo-user-units disable-now <unit>...
      paseo-user-units restart <unit>...
      paseo-user-units status <unit>...
      paseo-user-units list-timers
    EOF
      exit 2
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift

    case "$command" in
      reload)
        [ "$#" -eq 0 ] || usage
        systemctl_user daemon-reload
        ;;
      enable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user enable --now "$@"
        ;;
      disable-now)
        [ "$#" -ge 1 ] || usage
        systemctl_user disable --now "$@"
        systemctl_user daemon-reload
        ;;
      restart)
        [ "$#" -ge 1 ] || usage
        systemctl_user daemon-reload
        systemctl_user restart "$@"
        ;;
      status)
        [ "$#" -ge 1 ] || usage
        systemctl_user status --no-pager "$@"
        ;;
      list-timers)
        [ "$#" -eq 0 ] || usage
        systemctl_user list-timers --all --no-pager
        ;;
      *)
        usage
        ;;
    esac
  '';

  paseoRunHooks = pkgs.writeShellScriptBin "paseo-run-hooks" ''
    set -eu

    hook_set="''${1:-}"
    if [ -z "$hook_set" ]; then
      printf 'usage: paseo-run-hooks <hook-set>\n' >&2
      exit 2
    fi

    ${paseoRuntimeEnv}
    export PASEO_HOOK_SET="$hook_set"

    hook_dir="$HOME/.paseo-container/hooks/$hook_set"
    log_file="$HOME/.paseo-container/logs/paseo-hooks.log"
    mkdir -p "$(dirname "$log_file")" "$hook_dir"

    log_info() {
      printf '%s %s: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$hook_set" "$1" >> "$log_file"
    }

    if [ ! -d "$hook_dir" ]; then
      log_info "missing hook directory; skipping"
      exit 0
    fi

    found=0
    for hook in "$hook_dir"/*; do
      if [ ! -f "$hook" ] || [ ! -x "$hook" ]; then
        continue
      fi

      found=1
      log_info "running $(basename "$hook")"
      if "$hook" >> "$log_file" 2>&1; then
        log_info "completed $(basename "$hook")"
      else
        hook_status="$?"
        log_info "failed $(basename "$hook") with status $hook_status; continuing"
      fi
    done

    if [ "$found" -eq 0 ]; then
      log_info "no executable hooks"
    fi
  '';

  paseoDoctor = pkgs.writeShellScriptBin "paseo-doctor" ''
    set -eu

    ${paseoRuntimeEnv}

    su-exec paseo:paseo ${paseoToolMaintenance}/bin/paseo-tool-maintenance
    ${paseoRunHooks}/bin/paseo-run-hooks doctor.d
  '';

  paseoBootstrap = pkgs.writeShellScriptBin "paseo-bootstrap" ''
    set -eu

    ${paseoRuntimeEnv}

    ${paseoRunHooks}/bin/paseo-run-hooks bootstrap.d
    ${paseoRunHooks}/bin/paseo-run-hooks before-paseo.d
  '';

  paseoSnapshotConfig = pkgs.writeShellScriptBin "paseo-snapshot-config" ''
    set -eu

    ${paseoRuntimeEnv}

    recovery_dir="$HOME/.paseo-container/recovery"
    last_good="$recovery_dir/last-good"
    tmp="$recovery_dir/last-good.tmp"

    mkdir -p "$recovery_dir"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    ${paseoProviderCheck}
    for _ in $(seq 1 90); do
      if curl -fsS --max-time 5 http://127.0.0.1:6767/api/health >/dev/null \
        && paseo_providers_healthy; then
        break
      fi
      sleep 1
    done
    curl -fsS --max-time 5 http://127.0.0.1:6767/api/health >/dev/null
    paseo_providers_healthy

    mkdir -p "$tmp/home"
    for relative in \
      .paseo/config.json \
      .codex/config.toml \
      .config/opencode/opencode.json \
      .gemini/antigravity-cli/settings.json; do
      if [ -f "$HOME/$relative" ]; then
        mkdir -p "$tmp/home/$(dirname "$relative")"
        cp -a "$HOME/$relative" "$tmp/home/$relative"
      fi
    done

    rm -rf "$last_good"
    mv "$tmp" "$last_good"
  '';

  paseoTunnel = pkgs.writeShellScriptBin "paseo-tunnel" ''
    set -eu

    ${paseoRuntimeEnv}

    tunnel_dir="$HOME/.paseo-container/tunnels"
    unit_dir="$HOME/.config/systemd/user"
    log_dir="$HOME/.paseo-container/logs/tunnels"

    usage() {
      cat >&2 <<EOF
    usage:
      paseo-tunnel start <name> <port>
      paseo-tunnel stop <name>
      paseo-tunnel restart <name> <port>
      paseo-tunnel status <name>
      paseo-tunnel url <name>
      paseo-tunnel list
      paseo-tunnel remove <name>
    EOF
      exit 2
    }

    ensure_state() {
      mkdir -p "$tunnel_dir" "$unit_dir" "$log_dir"
    }

    validate_name() {
      name="$1"
      case "$name" in
        ""|"-"*|*"-"|*[!a-z0-9-]*)
          printf 'error: name must be a lowercase DNS label using a-z, 0-9, and hyphen\n' >&2
          exit 2
          ;;
      esac
      if [ "''${#name}" -gt 63 ]; then
        printf 'error: name must be 63 characters or fewer\n' >&2
        exit 2
      fi
    }

    validate_port() {
      case "$1" in
        ""|*[!0-9]*)
          printf 'error: port must be numeric\n' >&2
          exit 2
          ;;
      esac
      if [ "$1" -lt 1 ] || [ "$1" -gt 65535 ]; then
        printf 'error: port must be between 1 and 65535\n' >&2
        exit 2
      fi
    }

    unit_name() {
      printf 'paseo-tunnel-%s.service' "$1"
    }

    unit_path() {
      printf '%s/%s' "$unit_dir" "$(unit_name "$1")"
    }

    log_path() {
      printf '%s/%s.log' "$log_dir" "$1"
    }

    write_unit() {
      name="$1"
      port="$2"
      ensure_state
      validate_name "$name"
      validate_port "$port"
      log_file="$(log_path "$name")"
      cat > "$(unit_path "$name")" <<EOF
    [Unit]
    Description=Paseo quick tunnel: $name
    After=default.target

    [Service]
    Type=simple
    ExecStart=${pkgs.cloudflared}/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:$port
    Restart=always
    RestartSec=5
    StandardOutput=append:$log_file
    StandardError=append:$log_file

    [Install]
    WantedBy=default.target
    EOF
      printf '%s\t%s\n' "$name" "$port" > "$tunnel_dir/$name.tsv"
    }

    systemctl_user() {
      systemctl --user "$@"
    }

    start_tunnel() {
      [ "$#" -eq 2 ] || usage
      name="$1"
      port="$2"
      write_unit "$name" "$port"
      systemctl_user daemon-reload
      systemctl_user enable --now "$(unit_name "$name")"
      printf 'started %s for http://127.0.0.1:%s\n' "$name" "$port"
      printf 'logs: %s\n' "$(log_path "$name")"
    }

    stop_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user stop "$(unit_name "$name")" || true
    }

    restart_tunnel() {
      [ "$#" -eq 2 ] || usage
      stop_tunnel "$1"
      start_tunnel "$1" "$2"
    }

    status_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user status --no-pager "$(unit_name "$name")"
    }

    url_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      log_file="$(log_path "$name")"
      if [ ! -f "$log_file" ]; then
        printf 'error: no log file for tunnel %s\n' "$name" >&2
        exit 1
      fi
      url="$(grep -Eo 'https://[-a-zA-Z0-9.]+\\.trycloudflare\\.com' "$log_file" | tail -n 1 || true)"
      if [ -z "$url" ]; then
        printf 'error: no quick tunnel URL found yet for %s\n' "$name" >&2
        exit 1
      fi
      printf '%s\n' "$url"
    }

    list_tunnels() {
      [ "$#" -eq 0 ] || usage
      ensure_state
      found=0
      for entry in "$tunnel_dir"/*.tsv; do
        [ -f "$entry" ] || continue
        found=1
        IFS="$(printf '\t')" read -r name port < "$entry"
        state="$(systemctl_user is-active "$(unit_name "$name")" 2>/dev/null || true)"
        printf '%s\t%s\t%s' "$name" "$port" "$state"
        if url="$(paseo-tunnel url "$name" 2>/dev/null)"; then
          printf '\t%s' "$url"
        fi
        printf '\n'
      done
      [ "$found" -eq 1 ] || true
    }

    remove_tunnel() {
      [ "$#" -eq 1 ] || usage
      name="$1"
      validate_name "$name"
      systemctl_user disable --now "$(unit_name "$name")" || true
      rm -f "$(unit_path "$name")" "$tunnel_dir/$name.tsv"
      systemctl_user daemon-reload
    }

    [ "$#" -ge 1 ] || usage
    command="$1"
    shift
    case "$command" in
      start) start_tunnel "$@" ;;
      stop) stop_tunnel "$@" ;;
      restart) restart_tunnel "$@" ;;
      status) status_tunnel "$@" ;;
      url) url_tunnel "$@" ;;
      list|ls) list_tunnels "$@" ;;
      remove|rm|delete) remove_tunnel "$@" ;;
      *) usage ;;
    esac
  '';

  paseoDaemonRun = pkgs.writeShellScriptBin "paseo-daemon-run" ''
    set -eu

    ${paseoRuntimeEnv}
    export XDG_RUNTIME_DIR=/run/user/3000
    unset PASEO_PASSWORD
    cd /home/paseo

    exec paseo daemon start \
      --foreground \
      --web-ui \
      --no-relay \
      --hostnames paseo,paseo.ghostship.io,127.0.0.1,localhost
  '';

  paseoContainerSetup = pkgs.writeShellScriptBin "paseo-container-setup" ''
    set -eu

    ${paseoRuntimeEnv}

    mkdir -p \
      "$HOME/.local/bin" \
      "$NPM_CONFIG_PREFIX/bin" \
      "$NPM_CONFIG_PREFIX/lib" \
      "$XDG_DATA_HOME" \
      "$XDG_STATE_HOME" \
      "$XDG_CACHE_HOME" \
      "$HOME/.paseo" \
      "$HOME/.paseo-container/logs" \
      "$HOME/.paseo-container/recovery" \
      "$HOME/.paseo-container/tunnels" \
      "$HOME/.paseo-container/logs/tunnels" \
      "$HOME/.paseo-container/hooks/bootstrap.d" \
      "$HOME/.paseo-container/hooks/before-paseo.d" \
      "$HOME/.paseo-container/hooks/doctor.d" \
      "$HOME/.codex" \
      "$HOME/.gemini/antigravity-cli" \
      "$HOME/.local/share/keyrings" \
      "$HOME/.config/opencode" \
      "$HOME/.automation" \
      "$HOME/.config/systemd/user" \
      /workspace \
      /mnt/share \
      /var/lib/docker \
      /var/run \
      /tmp \
      /run/user/3000
    chown -R paseo:paseo \
      "$HOME/.local" \
      "$HOME/.config" \
      "$HOME/.cache" \
      "$HOME/.automation" \
      "$HOME/.paseo" \
      "$HOME/.paseo-container" \
      "$HOME/.codex" \
      "$HOME/.gemini" \
      "$HOME/.local/share/keyrings" \
      "$HOME/.config/systemd"
    chown paseo:paseo /run/user/3000
    chmod 0700 /run/user/3000
    if [ ! -e "$HOME/tools" ] && [ -d /workspace/ghostship-agent/tools ]; then
      ln -s /workspace/ghostship-agent/tools "$HOME/tools"
      chown -h paseo:paseo "$HOME/tools"
    fi
    if [ ! -x "$NPM_CONFIG_PREFIX/bin/paseo" ] \
      || [ ! -x "$NPM_CONFIG_PREFIX/bin/codex" ] \
      || [ ! -x "$NPM_CONFIG_PREFIX/bin/opencode" ] \
      || ! su-exec paseo:paseo "$HOME/.local/bin/agy" --version >/dev/null 2>&1; then
      su-exec paseo:paseo ${paseoToolMaintenance}/bin/paseo-tool-maintenance
    fi
    cat > "$HOME/.local/bin/paseo-daemon-run" <<'EOF'
    #!/bin/sh
    exec ${paseoDaemonRun}/bin/paseo-daemon-run "$@"
    EOF
    chown paseo:paseo "$HOME/.local/bin/paseo-daemon-run"
    chmod 0755 "$HOME/.local/bin/paseo-daemon-run"
    cat > "$HOME/.local/bin/paseo-tunnel" <<'EOF'
    #!/bin/sh
    exec ${paseoTunnel}/bin/paseo-tunnel "$@"
    EOF
    chown paseo:paseo "$HOME/.local/bin/paseo-tunnel"
    chmod 0755 "$HOME/.local/bin/paseo-tunnel"
    cat > "$HOME/.local/bin/paseo-user-units" <<'EOF'
    #!/bin/sh
    exec ${paseoUserUnits}/bin/paseo-user-units "$@"
    EOF
    chown paseo:paseo "$HOME/.local/bin/paseo-user-units"
    chmod 0755 "$HOME/.local/bin/paseo-user-units"
    cat > "$HOME/.local/bin/paseo-apply-config" <<'EOF'
    #!/bin/sh
    exec ${paseoApplyConfig}/bin/paseo-apply-config "$@"
    EOF
    chown paseo:paseo "$HOME/.local/bin/paseo-apply-config"
    chmod 0755 "$HOME/.local/bin/paseo-apply-config"
    rm -f "$HOME/.local/bin/paseo-proxy"

  '';

  paseoDockerdRun = pkgs.writeShellScriptBin "paseo-dockerd-run" ''
    set -eu

    ${paseoRuntimeEnv}

    rm -f /var/run/docker.pid
    exec dockerd \
      --host=unix:///var/run/docker.sock \
      --group=paseo \
      --data-root=/var/lib/docker \
      --storage-driver=vfs \
      --iptables=false \
      --ip-masq=false \
      --bridge=none
  '';

  paseoEntrypoint = pkgs.writeShellScriptBin "paseo-systemd-entrypoint" ''
    set -eu

    exec ${pkgs.systemd}/lib/systemd/systemd
  '';

  paseoImageContents = paseoPackages ++ [
    paseoEntrypoint
    paseoContainerSetup
    paseoDockerdRun
    paseoDaemonRun
    paseoToolMaintenance
    paseoToolAutoUpdate
    paseoToolUpdateRestart
    paseoQueueBootstrapRestart
    paseoDaemonMonitor
    paseoContainerHealth
    paseoRunHooks
    paseoDoctor
    paseoApplyConfig
    paseoUserUnits
    paseoBootstrap
    paseoSnapshotConfig
    paseoTunnel
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  paseoImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = paseoImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/paseo
      mkdir -p mnt/share run/user var/empty var/lib/docker var/log/journal var/run
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      paseo:x:3000:3000:Paseo:/home/paseo:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      paseo:x:3000:
      EOF
      nixbld_members=""
      nixbld_index=1
      while [ "$nixbld_index" -le 32 ]; do
        printf 'nixbld%s:x:%s:30000:Nix build user %s:/var/empty:/bin/sh\n' \
          "$nixbld_index" "$((30000 + nixbld_index))" "$nixbld_index" >> etc/passwd
        if [ -n "$nixbld_members" ]; then
          nixbld_members="$nixbld_members,"
        fi
        nixbld_members="$nixbld_members""nixbld$nixbld_index"
        nixbld_index="$((nixbld_index + 1))"
      done
      printf 'nixbld:x:30000:%s\n' "$nixbld_members" >> etc/group
      cat > etc/nix/nix.conf <<'EOF'
      experimental-features = nix-command flakes
      sandbox = false
      allowed-users = root paseo
      trusted-users = root
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/paseo-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/paseo-apply-config <<'EOF'
      paseo ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed paseo-daemon.service
      paseo ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart paseo-daemon.service
      EOF
      chmod 0440 etc/sudoers.d/paseo-apply-config
      rm -f etc/pam.d/systemd-user
      cat > etc/pam.d/systemd-user <<'EOF'
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      cat > etc/pam.d/sudo <<'EOF'
      auth sufficient ${pkgs.pam}/lib/security/pam_permit.so
      account required ${pkgs.pam}/lib/security/pam_permit.so
      session required ${pkgs.pam}/lib/security/pam_permit.so
      EOF
      for system_unit in halt.target shutdown.target final.target systemd-halt.service umount.target; do
        cp -a "${pkgs.systemd}/example/systemd/system/$system_unit" etc/systemd/system/
      done
      cp -a ${pkgs.systemd}/example/systemd/user/. usr/share/systemd/user/
      rm -f etc/systemd/user/dbus.socket etc/systemd/user/dbus.service etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/user/dbus.socket <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus Socket

      [Socket]
      ListenStream=%t/bus
      ExecStartPost=-${pkgs.systemd}/bin/systemctl --user set-environment DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus

      [Install]
      WantedBy=sockets.target
      EOF
      cat > etc/systemd/user/dbus.service <<'EOF'
      [Unit]
      Description=D-Bus User Message Bus
      Documentation=man:dbus-daemon(1)
      Requires=dbus.socket

      [Service]
      Type=notify
      NotifyAccess=main
      ExecStart=${pkgs.dbus}/bin/dbus-daemon --session --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only
      ExecReload=${pkgs.dbus}/bin/dbus-send --print-reply --session --type=method_call --dest=org.freedesktop.DBus / org.freedesktop.DBus.ReloadConfig
      Slice=session.slice
      EOF
      ln -s ../dbus.socket etc/systemd/user/sockets.target.wants/dbus.socket
      cat > etc/systemd/system/paseo-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare Paseo container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${paseoContainerSetup}/bin/paseo-container-setup
      RemainAfterExit=yes
      TimeoutStartSec=20m
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.service <<'EOF'
      [Unit]
      Description=Nix package manager daemon
      DefaultDependencies=no
      After=paseo-container-setup.service nix-daemon.socket
      Requires=paseo-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service paseo-secret-service.service paseo-bootstrap.service paseo-daemon.service shutdown.target

      [Service]
      Type=simple
      ExecStart=@${pkgs.nix}/bin/nix-daemon nix-daemon --daemon
      KillMode=mixed
      LimitNOFILE=1048576
      Delegate=yes
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/nix-daemon.socket <<'EOF'
      [Unit]
      Description=Nix package manager daemon socket
      DefaultDependencies=no
      After=paseo-container-setup.service
      Requires=paseo-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service paseo-secret-service.service paseo-bootstrap.service paseo-daemon.service shutdown.target

      [Socket]
      ListenStream=/nix/var/nix/daemon-socket/socket
      SocketMode=0666
      DirectoryMode=0755
      RemoveOnStop=true

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/user@.service <<'EOF'
      [Unit]
      Description=Paseo user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=paseo-container-setup.service nix-daemon.socket
      Requires=paseo-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=paseo-secret-service.service paseo-bootstrap.service paseo-daemon.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/paseo
      Environment=USER=paseo
      Environment=LOGNAME=paseo
      Environment=XDG_RUNTIME_DIR=/run/user/%i
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%i/bus
      Environment=NIX_REMOTE=daemon
      ExecStart=${pkgs.systemd}/lib/systemd/systemd --user
      Slice=user-%i.slice
      ReloadSignal=RTMIN+25
      KillMode=mixed
      Delegate=pids memory cpu
      DelegateSubgroup=init.scope
      TasksMax=infinity
      TimeoutStopSec=10s
      KeyringMode=inherit
      OOMScoreAdjust=100
      MemoryPressureWatch=skip
      Restart=always
      RestartSec=5

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-secret-service.service <<'EOF'
      [Unit]
      Description=Paseo Secret Service for Antigravity credentials
      DefaultDependencies=no
      After=paseo-container-setup.service user@3000.service
      Requires=paseo-container-setup.service user@3000.service
      Conflicts=shutdown.target
      Before=paseo-bootstrap.service paseo-daemon.service shutdown.target

      [Service]
      Type=simple
      User=paseo
      Group=paseo
      Environment=HOME=/home/paseo
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=GNOME_KEYRING_CONTROL=/run/user/3000/keyring
      ExecStart=${pkgs.gnome-keyring}/bin/gnome-keyring-daemon --foreground --components=secrets --control-directory=/run/user/3000/keyring
      Restart=always
      RestartSec=5
      TimeoutStopSec=10s

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/dockerd.service <<'EOF'
      [Unit]
      Description=Paseo Docker daemon
      DefaultDependencies=no
      After=paseo-container-setup.service
      Requires=paseo-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      ExecStart=${paseoDockerdRun}/bin/paseo-dockerd-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-bootstrap.service <<'EOF'
      [Unit]
      Description=Run Paseo bootstrap hooks
      DefaultDependencies=no
      After=paseo-container-setup.service nix-daemon.socket user@3000.service paseo-secret-service.service dockerd.service paseo-daemon.service
      Requires=paseo-container-setup.service nix-daemon.socket user@3000.service paseo-secret-service.service dockerd.service
      Wants=paseo-daemon.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      User=paseo
      Group=paseo
      Environment=HOME=/home/paseo
      Environment=USER=paseo
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/paseo/.automation
      Environment=PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin
      ExecStart=${paseoBootstrap}/bin/paseo-bootstrap
      ExecStartPost=+${paseoQueueBootstrapRestart}/bin/paseo-queue-bootstrap-restart
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/paseo/.paseo-container/logs/paseo-bootstrap.log
      StandardError=append:/home/paseo/.paseo-container/logs/paseo-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-daemon.service <<'EOF'
      [Unit]
      Description=Paseo daemon and bundled web UI
      DefaultDependencies=no
      After=paseo-container-setup.service user@3000.service paseo-secret-service.service dockerd.service
      Requires=paseo-container-setup.service user@3000.service paseo-secret-service.service dockerd.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      User=paseo
      Group=paseo
      Environment=HOME=/home/paseo
      Environment=USER=paseo
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/paseo/.automation
      Environment=PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin
      ExecStartPre=+${pkgs.coreutils}/bin/rm -f /run/paseo-tool-update/restart.pending
      ExecStart=${paseoDaemonRun}/bin/paseo-daemon-run
      ExecStartPost=${paseoSnapshotConfig}/bin/paseo-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=10s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/paseo/.paseo-container/logs/paseo-daemon.service.log
      StandardError=append:/home/paseo/.paseo-container/logs/paseo-daemon.service.log
      MemoryHigh=12G
      MemoryMax=16G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update Paseo, Codex, OpenCode, and Antigravity tools
      DefaultDependencies=no
      After=paseo-bootstrap.service
      Requires=paseo-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin
      ExecStart=${paseoToolAutoUpdate}/bin/paseo-tool-auto-update
      StandardOutput=append:/home/paseo/.paseo-container/logs/paseo-tool-auto-update.log
      StandardError=append:/home/paseo/.paseo-container/logs/paseo-tool-auto-update.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/paseo-tool-auto-update.timer <<'EOF'
      [Unit]
      Description=Periodic Paseo agent tool updates
      DefaultDependencies=no
      After=paseo-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=paseo-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart Paseo after queued maintenance becomes idle
      DefaultDependencies=no
      After=paseo-bootstrap.service
      Requires=paseo-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin
      ExecStart=${paseoToolUpdateRestart}/bin/paseo-tool-update-restart
      StandardOutput=append:/home/paseo/.paseo-container/logs/paseo-tool-update-restart.log
      StandardError=append:/home/paseo/.paseo-container/logs/paseo-tool-update-restart.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/paseo-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued Paseo maintenance when idle
      DefaultDependencies=no
      After=paseo-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=paseo-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/paseo-daemon-monitor.service <<'EOF'
      [Unit]
      Description=Monitor Paseo daemon and agent tools
      DefaultDependencies=no
      After=paseo-daemon.service
      Wants=paseo-daemon.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin
      ExecStart=${paseoDaemonMonitor}/bin/paseo-daemon-monitor
      StandardOutput=append:/home/paseo/.paseo-container/logs/paseo-daemon-monitor.log
      StandardError=append:/home/paseo/.paseo-container/logs/paseo-daemon-monitor.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/paseo-daemon-monitor.timer <<'EOF'
      [Unit]
      Description=Periodic Paseo daemon monitor
      DefaultDependencies=no
      After=paseo-daemon.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=paseo-daemon-monitor.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/multi-user.target <<'EOF'
      [Unit]
      Description=Paseo Multi-User System
      DefaultDependencies=no
      Wants=paseo-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service paseo-secret-service.service dockerd.service paseo-bootstrap.service paseo-daemon.service paseo-tool-auto-update.timer paseo-tool-update-restart.timer paseo-daemon-monitor.timer
      After=paseo-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../paseo-container-setup.service etc/systemd/system/multi-user.target.wants/paseo-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../paseo-secret-service.service etc/systemd/system/multi-user.target.wants/paseo-secret-service.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../paseo-bootstrap.service etc/systemd/system/multi-user.target.wants/paseo-bootstrap.service
      ln -s ../paseo-daemon.service etc/systemd/system/multi-user.target.wants/paseo-daemon.service
      ln -s ../paseo-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/paseo-tool-auto-update.timer
      ln -s ../paseo-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/paseo-tool-update-restart.timer
      ln -s ../paseo-daemon-monitor.timer etc/systemd/system/multi-user.target.wants/paseo-daemon-monitor.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${paseoEntrypoint}/bin/paseo-systemd-entrypoint" ];
      Env = [
        "HOME=/home/paseo"
        "USER=paseo"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/paseo/.config"
        "XDG_STATE_HOME=/home/paseo/.local/state"
        "XDG_CACHE_HOME=/home/paseo/.cache"
        "XDG_DATA_HOME=/home/paseo/.local/share"
        "NPM_CONFIG_PREFIX=/home/paseo/.local/share/paseo-tools/npm"
        "npm_config_prefix=/home/paseo/.local/share/paseo-tools/npm"
        "OPENCODE_AUTOMATION_DIR=/home/paseo/.automation"
        "PATH=/home/paseo/.local/bin:/home/paseo/.local/share/paseo-tools/npm/bin:${paseoPath}:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
        "PASEO_HOME=/home/paseo/.paseo"
        "PASEO_LISTEN=0.0.0.0:6767"
        "PASEO_WEB_UI_ENABLED=true"
        "AGY_CLI_DISABLE_AUTO_UPDATE=true"
      ];
      WorkingDir = "/home/paseo";
      ExposedPorts = {
        "6767/tcp" = { };
      };
    };
  };

in
{
  virtualisation.oci-containers.containers."paseo" = {
    image = "${imageName}:${imageTag}";
    imageFile = paseoImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=180"
      "--network=ghostship_net"
      "--health-cmd=${paseoContainerHealth}/bin/paseo-container-health"
      "--health-interval=30s"
      "--health-timeout=15s"
      "--health-retries=5"
      "--health-start-period=5m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${paseoDocker}:/var/lib/docker:rw"
      "${paseoWorkspace}:/workspace:rw"
      "${paseoHome}:/home/paseo:rw"
      "${paseoNixRoot}/nix:/nix:rw"
      "${paseoSecrets}:${paseoSecretsFile}:ro"
      "/mnt/share:/mnt/share:rw"
    ];
    environmentFiles = [ paseoSecrets ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/paseo 0755 root root -"
    "d ${paseoDocker} 0755 root root -"
    "d ${paseoHome} 0755 3000 3000 -"
    "d ${paseoNixRoot} 0755 root root -"
    "d ${paseoNixRoot}/nix 0755 root root -"
    "d ${paseoWorkspace} 0755 3000 3000 -"
  ];

  systemd.services.podman-paseo = {
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig.TimeoutStopSec = lib.mkForce "210s";
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/paseo
      install -d -m0755 -o root -g root ${paseoDocker}
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}
      install -d -m0755 -o root -g root ${paseoNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${paseoWorkspace}

      nix_store_uri='local?root=${paseoNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString paseoImageContents)}

      gcroot_dir=${paseoNixRoot}/nix/var/nix/gcroots/ghostship-paseo-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString paseoImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${paseoNixRoot}/nix/var/nix/temproots/*
      rm -rf ${paseoNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.config/opencode
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.codex
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.gemini/antigravity-cli
      install -d -m0700 -o 3000 -g 3000 ${paseoHome}/.local/share/keyrings
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.automation
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.config/systemd/user
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/logs/tunnels
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/recovery
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/tunnels
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/hooks/before-paseo.d
      install -d -m0755 -o 3000 -g 3000 ${paseoHome}/.paseo-container/hooks/doctor.d

      if [ -e ${paseoHome}/.config/systemd/user/paseo.service ] \
        && grep -q 'ExecStart=/home/paseo/.local/bin/paseo-daemon-run' ${paseoHome}/.config/systemd/user/paseo.service; then
        rm -f ${paseoHome}/.config/systemd/user/paseo.service
      fi
      if [ -e ${paseoHome}/.config/systemd/user/default.target ] \
        && grep -q 'Paseo User Default Target' ${paseoHome}/.config/systemd/user/default.target; then
        rm -f ${paseoHome}/.config/systemd/user/default.target
      fi
      rm -f ${paseoHome}/.config/systemd/user/default.target.wants/paseo.service
    '';
  };
}
