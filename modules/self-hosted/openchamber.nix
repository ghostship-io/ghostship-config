{
  config,
  lib,
  pkgs,
  ...
}:

let
  openchamberHome = "/srv/apps/openchamber/home";
  openchamberDocker = "/srv/apps/openchamber/docker";
  openchamberNixRoot = "/srv/apps/openchamber/nix-root";
  openchamberWorkspace = "/srv/apps/openchamber/workspace";
  openchamberSecrets = config.ghostship.selfHostedSecrets.projections.openchamber.path;
  openchamberSecretsFile = "/run/secrets/openchamber.env";
  openchamberDeploymentState = "/var/lib/ghostship/openchamber-deployment";
  imageName = "localhost/ghostship-openchamber";
  imageTag = "openchamber-runtime";
  openchamberOpenCodeConfig = builtins.toJSON {
    provider.openai.options = {
      headerTimeout = 60000;
      timeout = 600000;
      chunkTimeout = 60000;
    };
    compaction = {
      auto = true;
      prune = true;
      reserved = 20000;
    };
  };

  openchamberPackages = with pkgs; [
    nix
    systemd
    dbus
    pam
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
    if [ -f ${openchamberSecretsFile} ]; then
      set -a
      # shellcheck disable=SC1091
      . ${openchamberSecretsFile}
      set +a
    fi
    export HOME=/home/openchamber
    export USER=openchamber
    export XDG_CONFIG_HOME="''${XDG_CONFIG_HOME:-$HOME/.config}"
    export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
    export XDG_CACHE_HOME="''${XDG_CACHE_HOME:-$HOME/.cache}"
    export XDG_DATA_HOME="''${XDG_DATA_HOME:-$HOME/.local/share}"
    export NPM_CONFIG_PREFIX="$HOME/.local/share/openchamber-tools/npm"
    export npm_config_prefix="$NPM_CONFIG_PREFIX"
    export OPENCODE_AUTOMATION_DIR="$HOME/.automation"
    export OPENCODE_CONFIG_CONTENT=${lib.escapeShellArg openchamberOpenCodeConfig}
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
    export PATH=$HOME/.local/bin:$NPM_CONFIG_PREFIX/bin:${openchamberPath}:/bin:/usr/bin:$PATH
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

  openchamberIdleCheck = ''
    is_openchamber_idle() {
      if ! activity="$(${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/api/session-activity)"; then
        return 1
      fi

      printf '%s\n' "$activity" | ${pkgs.jq}/bin/jq -e '
        if type != "object" then
          false
        else
          all(.[]; type == "object" and .type == "idle")
        end
      ' >/dev/null 2>&1
    }
  '';

  openchamberToolMaintenance = pkgs.writeShellScriptBin "openchamber-tool-maintenance" ''
    set -eu

    ${openchamberRuntimeEnv}
    export NODE_NO_WARNINGS=1

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >&2
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

    state_dir="/run/openchamber-tool-update"
    pending_restart="$state_dir/restart.pending"
    install -d -m 0700 "$state_dir"

    exec 9>"$state_dir/tool-update.lock"
    ${pkgs.util-linux}/bin/flock 9

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >&2
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
      pending_tmp="$pending_restart.tmp"
      {
        printf 'source=tool-update\n'
        printf 'queued_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        printf 'previous_openchamber=%s\n' "$before_openchamber"
        printf 'previous_opencode=%s\n' "$before_opencode"
        printf 'openchamber=%s\n' "$after_openchamber"
        printf 'opencode=%s\n' "$after_opencode"
      } > "$pending_tmp"
      mv "$pending_tmp" "$pending_restart"
      log_info "tool update downloaded; queued restart until OpenChamber is idle"
    else
      log_info "installed tool versions are unchanged"
    fi
  '';

  openchamberToolUpdateRestart = pkgs.writeShellScriptBin "openchamber-tool-update-restart" ''
    set -eu

    ${openchamberRuntimeEnv}

    state_dir="/run/openchamber-tool-update"
    pending_restart="$state_dir/restart.pending"
    audit_log="$HOME/.config/openchamber/logs/restart-audit.log"
    mkdir -p "$(dirname "$audit_log")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >&2
    }

    audit_restart() {
      reason="$(tr '\n' ' ' < "$pending_restart")"
      printf '%s source=queued-maintenance action=restart-web %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$reason" >> "$audit_log"
    }

    ${openchamberIdleCheck}

    [ -f "$pending_restart" ] || exit 0

    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "tool maintenance is still running; leaving restart queued"
      exit 0
    fi

    if ! systemctl is-active --quiet openchamber-web.service; then
      log_info "openchamber-web.service is stopped; clearing queued restart"
      rm -f "$pending_restart"
      exit 0
    fi

    if ! is_openchamber_idle; then
      log_info "OpenChamber reports active or unknown work; leaving restart queued"
      exit 0
    fi

    log_info "OpenChamber is idle; requiring 30 seconds of continuous idle before restart"
    sleep 30

    if [ ! -f "$pending_restart" ]; then
      log_info "queued restart was already applied by another service start"
      exit 0
    fi

    if ! is_openchamber_idle; then
      log_info "OpenChamber is no longer idle; leaving restart queued"
      exit 0
    fi

    log_info "OpenChamber remained idle for 30 seconds; applying queued maintenance restart"
    audit_restart
    systemctl restart openchamber-web.service
    rm -f "$pending_restart"
  '';

  openchamberRetryGuard = pkgs.writeShellScriptBin "openchamber-retry-guard" ''
    set -eu

    ${openchamberRuntimeEnv}

    state_dir="/run/openchamber-retry-guard"
    state_file="$state_dir/state.json"
    log_file="$HOME/.config/openchamber/logs/openchamber-retry-guard.log"
    install -d -m 0700 "$state_dir"
    mkdir -p "$(dirname "$log_file")"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    if ! snapshot="$(curl -fsS --max-time 10 http://127.0.0.1:3000/api/sessions/status)"; then
      log_info "session status unavailable; retry guard deferred"
      exit 0
    fi

    previous='{}'
    if [ -f "$state_file" ] && jq -e 'type == "object"' "$state_file" >/dev/null 2>&1; then
      previous="$(cat "$state_file")"
    fi

    now_ms="$(($(date -u '+%s') * 1000))"
    next_state="$(
      printf '%s\n' "$snapshot" | jq -c \
        --argjson now "$now_ms" \
        --argjson previous "$previous" '
          reduce (
            .sessions
            | to_entries[]
            | select(.value.status == "retry")
          ) as $item (
            {};
            .[$item.key] = {
              firstSeen: ($previous[$item.key].firstSeen // $now),
              attempt: ($item.value.metadata.attempt // 0),
              message: ($item.value.metadata.message // "provider retry")
            }
          )
        '
    )"

    printf '%s\n' "$next_state" > "$state_file.tmp"
    mv "$state_file.tmp" "$state_file"

    printf '%s\n' "$next_state" | jq -r 'to_entries[] | @base64' |
      while IFS= read -r encoded; do
        entry="$(printf '%s' "$encoded" | base64 -d)"
        session_id="$(printf '%s' "$entry" | jq -r '.key')"
        first_seen="$(printf '%s' "$entry" | jq -r '.value.firstSeen')"
        attempt="$(printf '%s' "$entry" | jq -r '.value.attempt')"
        message="$(printf '%s' "$entry" | jq -r '.value.message')"
        age_ms="$((now_ms - first_seen))"

        if [ "$attempt" -lt 10 ] && [ "$age_ms" -lt 600000 ]; then
          continue
        fi

        if ! session="$(curl -fsS --max-time 10 "http://127.0.0.1:3000/api/session/$session_id")"; then
          log_info "session=$session_id retry guard could not resolve session directory"
          continue
        fi
        directory="$(printf '%s\n' "$session" | jq -r '.directory // empty')"
        if [ -z "$directory" ]; then
          log_info "session=$session_id retry guard found no session directory"
          continue
        fi
        encoded_directory="$(printf '%s' "$directory" | jq -sRr @uri)"

        if curl -fsS --max-time 15 -X POST \
          "http://127.0.0.1:3000/api/session/$session_id/abort?directory=$encoded_directory" >/dev/null; then
          log_info "session=$session_id action=abort-provider-retry attempt=$attempt age_ms=$age_ms reason=$message"
        else
          log_info "session=$session_id provider retry abort failed; will retry"
        fi
      done
  '';

  openchamberReconcileInterruptedTools = pkgs.writeShellScriptBin "openchamber-reconcile-interrupted-tools" ''
    set -eu

    ${openchamberRuntimeEnv}

    web_is_running=0
    if curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
      web_is_running=1
    else
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null |
          grep -Eq '(/| )openchamber serve|opencode serve'; then
          web_is_running=1
          break
        fi
      done
    fi

    if [ "$web_is_running" -eq 1 ]; then
      printf 'info: OpenChamber runtime is active; orphan reconciliation skipped\n'
      exit 0
    fi

    count_query="$(cat <<'SQL'
    SELECT count(*) AS count
    FROM part
    WHERE json_extract(data, '$.type') = 'tool'
      AND json_extract(data, '$.state.status') IN ('running', 'pending');
    SQL
    )"
    count="$(
      opencode db --format json "$count_query" |
        jq -r '.[0].count // 0'
    )"

    case "$count" in
      0) exit 0 ;;
      ""|*[!0-9]*)
        printf 'warning: could not count orphaned OpenCode tools\n' >&2
        exit 0
        ;;
    esac

    update_query="$(cat <<'SQL'
    UPDATE part
    SET data = json_set(
      data,
      '$.state.status', 'error',
      '$.state.error', 'Interrupted by an OpenChamber service restart',
      '$.state.time.end', CAST(strftime('%s', 'now') AS INTEGER) * 1000
    )
    WHERE json_extract(data, '$.type') = 'tool'
      AND json_extract(data, '$.state.status') IN ('running', 'pending');
    SQL
    )"
    opencode db "$update_query" >/dev/null
    printf 'info: reconciled %s orphaned OpenCode tool records\n' "$count"
  '';

  openchamberWebMonitor = pkgs.writeShellScriptBin "openchamber-web-monitor" ''
    set -eu

    ${openchamberRuntimeEnv}

    log_file="$HOME/.config/openchamber/logs/openchamber-web-monitor.log"
    state_dir="/run/openchamber-web-monitor"
    state_file="$state_dir/failure-state"
    mkdir -p "$(dirname "$log_file")"
    install -d -m 0700 "$state_dir"

    log_info() {
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }

    ${openchamberIdleCheck}

    unhealthy_reason=""
    web_was_active=1

    if ! systemctl is-active --quiet openchamber-web.service; then
      unhealthy_reason="openchamber-web.service is not active"
      web_was_active=0
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
      rm -f "$state_file"
      log_info "healthy"
      exit 0
    fi

    previous_reason=""
    previous_count=0
    if [ -f "$state_file" ]; then
      IFS="$(printf '\t')" read -r previous_count previous_reason < "$state_file" || true
    fi
    if [ "$previous_reason" = "$unhealthy_reason" ]; then
      failure_count="$((previous_count + 1))"
    else
      failure_count=1
    fi
    printf '%s\t%s\n' "$failure_count" "$unhealthy_reason" > "$state_file.tmp"
    mv "$state_file.tmp" "$state_file"

    if [ "$failure_count" -lt 3 ]; then
      log_info "unhealthy: $unhealthy_reason; consecutive failure $failure_count/3; restart deferred"
      exit 0
    fi

    if [ "$web_was_active" -eq 1 ] && ! is_openchamber_idle; then
      log_info "unhealthy: $unhealthy_reason; OpenChamber activity is active or unknown; restart deferred"
      exit 0
    fi

    state_dir="/run/openchamber-tool-update"
    install -d -m 0700 "$state_dir"
    exec 9>"$state_dir/tool-update.lock"
    if ! ${pkgs.util-linux}/bin/flock -n 9; then
      log_info "unhealthy: $unhealthy_reason; tool maintenance or restart is in progress; restart deferred"
      exit 0
    fi

    log_info "unhealthy: $unhealthy_reason; restarting openchamber-web.service"
    printf '%s source=health-monitor action=restart-web reason=%s failures=%s\n' \
      "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$unhealthy_reason" "$failure_count" \
      >> "$HOME/.config/openchamber/logs/restart-audit.log"
    systemctl reset-failed openchamber-web.service || true
    systemctl restart openchamber-web.service
    rm -f "$state_file"
  '';

  openchamberContainerHealth = pkgs.writeShellScriptBin "openchamber-container-health" ''
    set -eu

    ${openchamberIdleCheck}

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
    if ! setup_state="$(${pkgs.systemd}/bin/systemctl show openchamber-container-setup.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! bootstrap_state="$(${pkgs.systemd}/bin/systemctl show openchamber-bootstrap.service -p ActiveState --value)"; then
      exit 0
    fi
    if ! web_state="$(${pkgs.systemd}/bin/systemctl show openchamber-web.service -p ActiveState --value)"; then
      exit 0
    fi

    if [ "$container_age_seconds" -lt 1200 ] \
      && { [ "$setup_state" = "activating" ] \
        || [ "$bootstrap_state" = "activating" ] \
        || [ "$web_state" = "activating" ]; }; then
      exit 0
    fi

    if ${pkgs.curl}/bin/curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null; then
      exit 0
    fi

    if ! ${pkgs.systemd}/bin/systemctl is-active --quiet openchamber-web.service; then
      exit 1
    fi

    if is_openchamber_idle; then
      exit 1
    fi

    printf 'warning: OpenChamber health is degraded but activity is active or unknown; container kill deferred\n' >&2
    exit 0
  '';

  openchamberApplyConfig = pkgs.writeShellScriptBin "openchamber-apply-config" ''
    set -eu

    ${openchamberRuntimeEnv}

    recovery_dir="$HOME/.config/openchamber/recovery"
    last_good="$recovery_dir/last-good"
    log_file="$HOME/.config/openchamber/logs/openchamber-apply-config.log"
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

      mkdir -p "$HOME/.config/openchamber"
      find "$HOME/.config/openchamber" -mindepth 1 -maxdepth 1 \
        ! -name logs \
        ! -name run \
        ! -name recovery \
        -exec rm -rf {} +

      if [ -d "$src/openchamber" ]; then
        tar -C "$src" -cf - openchamber | tar -C "$HOME/.config" -xf -
      fi

      rm -rf "$HOME/.config/opencode"
      if [ -d "$src/opencode" ]; then
        tar -C "$src" -cf - opencode | tar -C "$HOME/.config" -xf -
      else
        mkdir -p "$HOME/.config/opencode"
      fi

      rm -rf "$HOME/.openchamber"
      if [ -d "$src/.openchamber" ]; then
        tar -C "$src" -cf - .openchamber | tar -C "$HOME" -xf -
      else
        mkdir -p "$HOME/.openchamber/hooks/bootstrap.d" \
          "$HOME/.openchamber/hooks/before-openchamber.d" \
          "$HOME/.openchamber/hooks/doctor.d"
      fi
    }

    validate_json_tree() {
      dir="$1"
      [ -d "$dir" ] || return 0
      find "$dir" -type f -name '*.json' \
        ! -path "$HOME/.config/openchamber/logs/*" \
        ! -path "$HOME/.config/openchamber/run/*" \
        ! -path "$HOME/.config/openchamber/recovery/*" \
        -print | while IFS= read -r file; do
          if ! jq -e . "$file" >/dev/null; then
            log_error "invalid JSON: $file"
            exit 1
          fi
        done
    }

    validate_config() {
      command -v openchamber >/dev/null 2>&1 || {
        log_error "openchamber CLI is not installed"
        return 1
      }
      command -v opencode >/dev/null 2>&1 || {
        log_error "opencode CLI is not installed"
        return 1
      }

      validate_json_tree "$HOME/.config/openchamber"
      validate_json_tree "$HOME/.openchamber"
      opencode debug config >/dev/null
    }

    restart_web() {
      "$sudo_bin" -n "$systemctl_bin" reset-failed openchamber-web.service
      "$sudo_bin" -n "$systemctl_bin" restart openchamber-web.service
    }

    has_opencode_serve() {
      for cmdline in /proc/[0-9]*/cmdline; do
        if tr '\0' ' ' < "$cmdline" 2>/dev/null | grep -q 'opencode serve'; then
          return 0
        fi
      done
      return 1
    }

    wait_healthy() {
      for _ in $(seq 1 90); do
        if curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null && has_opencode_serve; then
          return 0
        fi
        sleep 1
      done
      return 1
    }

    apply_config() {
      log_info "validating OpenChamber and OpenCode config"
      validate_config

      if [ ! -d "$last_good" ]; then
        log_error "no last-good config snapshot exists; wait for openchamber-web.service to start successfully once"
        exit 1
      fi

      log_info "restarting openchamber-web.service"
      restart_web

      if wait_healthy; then
        log_info "OpenChamber and OpenCode are healthy"
        exit 0
      fi

      log_error "OpenChamber or OpenCode did not become healthy; restoring last-good config"
      restore_config "$last_good"
      validate_config
      restart_web

      if wait_healthy; then
        log_info "rollback restored a healthy OpenChamber runtime"
        exit 1
      fi

      log_error "rollback did not restore a healthy OpenChamber runtime"
      exit 1
    }

    case "''${1:-apply}" in
      apply) apply_config ;;
      *)
        printf 'usage: openchamber-apply-config [apply]\n' >&2
        exit 2
        ;;
    esac
  '';

  openchamberUserUnits = pkgs.writeShellScriptBin "openchamber-user-units" ''
    set -eu

    ${openchamberRuntimeEnv}

    usage() {
      cat >&2 <<EOF
    usage:
      openchamber-user-units reload
      openchamber-user-units enable-now <unit>...
      openchamber-user-units disable-now <unit>...
      openchamber-user-units restart <unit>...
      openchamber-user-units status <unit>...
      openchamber-user-units list-timers
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

  openchamberRunHooks = pkgs.writeShellScriptBin "openchamber-run-hooks" ''
    set -eu

    hook_set="''${1:-}"
    if [ -z "$hook_set" ]; then
      printf 'usage: openchamber-run-hooks <hook-set>\n' >&2
      exit 2
    fi

    ${openchamberRuntimeEnv}
    export OPENCHAMBER_HOOK_SET="$hook_set"

    hook_dir="$HOME/.openchamber/hooks/$hook_set"
    log_file="$HOME/.config/openchamber/logs/openchamber-hooks.log"
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

  openchamberDoctor = pkgs.writeShellScriptBin "openchamber-doctor" ''
    set -eu

    ${openchamberRuntimeEnv}

    su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
    ${openchamberRunHooks}/bin/openchamber-run-hooks doctor.d
  '';

  openchamberBootstrap = pkgs.writeShellScriptBin "openchamber-bootstrap" ''
    set -eu

    ${openchamberRuntimeEnv}

    ${openchamberReconcileInterruptedTools}/bin/openchamber-reconcile-interrupted-tools
    ${openchamberRunHooks}/bin/openchamber-run-hooks bootstrap.d
    ${openchamberRunHooks}/bin/openchamber-run-hooks before-openchamber.d
  '';

  openchamberSnapshotConfig = pkgs.writeShellScriptBin "openchamber-snapshot-config" ''
    set -eu

    ${openchamberRuntimeEnv}

    recovery_dir="$HOME/.config/openchamber/recovery"
    last_good="$recovery_dir/last-good"
    tmp="$recovery_dir/last-good.tmp"

    mkdir -p "$recovery_dir"
    rm -rf "$tmp"
    mkdir -p "$tmp"

    if [ -d "$HOME/.config/openchamber" ]; then
      tar -C "$HOME/.config" \
        --exclude='openchamber/logs' \
        --exclude='openchamber/run' \
        --exclude='openchamber/recovery' \
        -cf - openchamber | tar -C "$tmp" -xf -
    fi

    if [ -d "$HOME/.config/opencode" ]; then
      tar -C "$HOME/.config" -cf - opencode | tar -C "$tmp" -xf -
    fi

    if [ -d "$HOME/.openchamber" ]; then
      tar -C "$HOME" -cf - .openchamber | tar -C "$tmp" -xf -
    fi

    rm -rf "$last_good"
    mv "$tmp" "$last_good"
  '';

  openchamberTunnel = pkgs.writeShellScriptBin "openchamber-tunnel" ''
    set -eu

    ${openchamberRuntimeEnv}

    tunnel_dir="$HOME/.config/openchamber/tunnels"
    unit_dir="$HOME/.config/systemd/user"
    log_dir="$HOME/.config/openchamber/logs/tunnels"

    usage() {
      cat >&2 <<EOF
    usage:
      openchamber-tunnel start <name> <port>
      openchamber-tunnel stop <name>
      openchamber-tunnel restart <name> <port>
      openchamber-tunnel status <name>
      openchamber-tunnel url <name>
      openchamber-tunnel list
      openchamber-tunnel remove <name>
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
      printf 'openchamber-tunnel-%s.service' "$1"
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
    Description=OpenChamber quick tunnel: $name
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
        if url="$(openchamber-tunnel url "$name" 2>/dev/null)"; then
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

    mkdir -p \
      "$HOME/.local/bin" \
      "$NPM_CONFIG_PREFIX/bin" \
      "$NPM_CONFIG_PREFIX/lib" \
      "$XDG_DATA_HOME" \
      "$XDG_STATE_HOME" \
      "$XDG_CACHE_HOME" \
      "$HOME/.config/openchamber/logs" \
      "$HOME/.config/openchamber/recovery" \
      "$HOME/.config/openchamber/tunnels" \
      "$HOME/.config/openchamber/logs/tunnels" \
      "$HOME/.config/opencode" \
      "$HOME/.automation" \
      "$HOME/.config/systemd/user" \
      "$HOME/.openchamber/hooks/bootstrap.d" \
      "$HOME/.openchamber/hooks/before-openchamber.d" \
      "$HOME/.openchamber/hooks/doctor.d" \
      /workspace \
      /mnt/share \
      /var/lib/docker \
      /var/run \
      /tmp \
      /run/user/3000
    chown -R openchamber:openchamber "$HOME/.openchamber" "$HOME/.config/systemd"
    chown -R openchamber:openchamber "$HOME/.config/openchamber/logs" "$HOME/.config/openchamber/recovery" "$HOME/.config/openchamber/tunnels"
    chown openchamber:openchamber /run/user/3000
    chmod 0700 /run/user/3000
    if [ ! -e "$HOME/tools" ] && [ -d /workspace/ghostship-agent/tools ]; then
      ln -s /workspace/ghostship-agent/tools "$HOME/tools"
      chown -h openchamber:openchamber "$HOME/tools"
    fi
    rm -rf \
      "$HOME/.codex" \
      "$HOME/.gemini" \
      "$HOME/.local/state/codex" \
      "$HOME/.local/bin/codex" \
      "$HOME/.local/bin/gemini" \
      "$HOME/.local/bin/gemini-cli"
    if [ ! -x "$NPM_CONFIG_PREFIX/bin/openchamber" ] \
      || [ ! -x "$NPM_CONFIG_PREFIX/bin/opencode" ]; then
      su-exec openchamber:openchamber ${openchamberToolMaintenance}/bin/openchamber-tool-maintenance
    fi
    cat > "$HOME/.local/bin/openchamber-web-run" <<'EOF'
    #!/bin/sh
    exec ${openchamberWebRun}/bin/openchamber-web-run "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-web-run"
    chmod 0755 "$HOME/.local/bin/openchamber-web-run"
    cat > "$HOME/.local/bin/openchamber-tunnel" <<'EOF'
    #!/bin/sh
    exec ${openchamberTunnel}/bin/openchamber-tunnel "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-tunnel"
    chmod 0755 "$HOME/.local/bin/openchamber-tunnel"
    cat > "$HOME/.local/bin/openchamber-user-units" <<'EOF'
    #!/bin/sh
    exec ${openchamberUserUnits}/bin/openchamber-user-units "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-user-units"
    chmod 0755 "$HOME/.local/bin/openchamber-user-units"
    cat > "$HOME/.local/bin/openchamber-apply-config" <<'EOF'
    #!/bin/sh
    exec ${openchamberApplyConfig}/bin/openchamber-apply-config "$@"
    EOF
    chown openchamber:openchamber "$HOME/.local/bin/openchamber-apply-config"
    chmod 0755 "$HOME/.local/bin/openchamber-apply-config"
    rm -f "$HOME/.local/bin/openchamber-proxy"

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

  openchamberImageContents = openchamberPackages ++ [
    openchamberEntrypoint
    openchamberContainerSetup
    openchamberDockerdRun
    openchamberWebRun
    openchamberToolMaintenance
    openchamberToolAutoUpdate
    openchamberToolUpdateRestart
    openchamberRetryGuard
    openchamberReconcileInterruptedTools
    openchamberWebMonitor
    openchamberContainerHealth
    openchamberRunHooks
    openchamberDoctor
    openchamberApplyConfig
    openchamberUserUnits
    openchamberBootstrap
    openchamberSnapshotConfig
    openchamberTunnel
    pkgs.dockerTools.binSh
    pkgs.dockerTools.usrBinEnv
    pkgs.dockerTools.caCertificates
  ];

  openchamberImage = pkgs.dockerTools.buildLayeredImageWithNixDb {
    name = imageName;
    tag = imageTag;
    contents = openchamberImageContents;
    extraCommands = ''
      mkdir -p etc/nix etc/pam.d etc/sudoers.d etc/systemd/system/multi-user.target.wants etc/systemd/user/sockets.target.wants usr/bin usr/share/systemd/user nix/store nix/var/log/nix nix/var/nix tmp workspace home/openchamber
      mkdir -p mnt/share run/user var/empty var/lib/docker var/log/journal var/run
      chmod 1777 tmp
      chmod 0555 var/empty
      cp ${pkgs.sudo}/bin/sudo usr/bin/sudo
      chmod 0755 usr/bin/sudo
      cat > etc/passwd <<'EOF'
      root:x:0:0:root:/root:/bin/sh
      openchamber:x:3000:3000:OpenChamber:/home/openchamber:/bin/sh
      EOF
      cat > etc/group <<'EOF'
      root:x:0:
      openchamber:x:3000:
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
      allowed-users = root openchamber
      trusted-users = root
      build-users-group = nixbld
      EOF
      rm -f etc/sudoers etc/sudoers.d/openchamber-apply-config etc/pam.d/sudo
      cat > etc/sudoers <<'EOF'
      root ALL=(ALL:ALL) ALL
      #includedir /etc/sudoers.d
      EOF
      chmod 0440 etc/sudoers
      cat > etc/sudoers.d/openchamber-apply-config <<'EOF'
      openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl reset-failed openchamber-web.service
      openchamber ALL=(root) NOPASSWD: ${pkgs.systemd}/bin/systemctl restart openchamber-web.service
      EOF
      chmod 0440 etc/sudoers.d/openchamber-apply-config
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
      cat > etc/systemd/system/openchamber-container-setup.service <<'EOF'
      [Unit]
      Description=Prepare OpenChamber container state
      DefaultDependencies=no
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      ExecStart=${openchamberContainerSetup}/bin/openchamber-container-setup
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
      After=openchamber-container-setup.service nix-daemon.socket
      Requires=openchamber-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=user@3000.service openchamber-bootstrap.service openchamber-web.service shutdown.target

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
      After=openchamber-container-setup.service
      Requires=openchamber-container-setup.service
      Conflicts=shutdown.target
      Before=nix-daemon.service user@3000.service openchamber-bootstrap.service openchamber-web.service shutdown.target

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
      Description=OpenChamber user manager for UID %i
      Documentation=man:user@.service(5)
      DefaultDependencies=no
      After=openchamber-container-setup.service nix-daemon.socket
      Requires=openchamber-container-setup.service nix-daemon.socket
      Conflicts=shutdown.target
      Before=openchamber-bootstrap.service openchamber-web.service shutdown.target
      IgnoreOnIsolate=yes

      [Service]
      User=%i
      PAMName=systemd-user
      Type=notify-reload
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=LOGNAME=openchamber
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
      cat > etc/systemd/system/dockerd.service <<'EOF'
      [Unit]
      Description=OpenChamber Docker daemon
      DefaultDependencies=no
      After=openchamber-container-setup.service
      Requires=openchamber-container-setup.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      ExecStart=${openchamberDockerdRun}/bin/openchamber-dockerd-run
      Restart=always
      RestartSec=5
      TimeoutStopSec=30s
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-bootstrap.service <<'EOF'
      [Unit]
      Description=Run OpenChamber bootstrap hooks
      DefaultDependencies=no
      After=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Requires=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      Conflicts=shutdown.target
      Before=openchamber-web.service shutdown.target

      [Service]
      Type=oneshot
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecCondition=+${pkgs.runtimeShell} -c 'state="$(${pkgs.systemd}/bin/systemctl show openchamber-web.service -p ActiveState --value)" && { [ "$state" = inactive ] || [ "$state" = failed ]; }'
      ExecStart=${openchamberBootstrap}/bin/openchamber-bootstrap
      RemainAfterExit=yes
      TimeoutStartSec=20m
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-bootstrap.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-bootstrap.log
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-web.service <<'EOF'
      [Unit]
      Description=OpenChamber Web
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=simple
      User=openchamber
      Group=openchamber
      Environment=HOME=/home/openchamber
      Environment=USER=openchamber
      Environment=XDG_RUNTIME_DIR=/run/user/3000
      Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus
      Environment=OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStartPre=+${pkgs.coreutils}/bin/rm -f /run/openchamber-tool-update/restart.pending
      ExecStart=${openchamberWebRun}/bin/openchamber-web-run
      ExecStartPost=${openchamberSnapshotConfig}/bin/openchamber-snapshot-config
      Restart=always
      RestartSec=5
      TimeoutStartSec=20m
      TimeoutStopSec=30s
      SuccessExitStatus=0 143
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-web.service.log
      MemoryHigh=32G
      MemoryMax=40G
      OOMPolicy=continue
      TasksMax=infinity

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-tool-auto-update.service <<'EOF'
      [Unit]
      Description=Update OpenChamber and OpenCode tools
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

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
      After=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=10m
      OnUnitActiveSec=4h
      Persistent=true
      Unit=openchamber-tool-auto-update.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-tool-update-restart.service <<'EOF'
      [Unit]
      Description=Restart OpenChamber after queued maintenance becomes idle
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Requires=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberToolUpdateRestart}/bin/openchamber-tool-update-restart
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-update-restart.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-tool-update-restart.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-tool-update-restart.timer <<'EOF'
      [Unit]
      Description=Apply queued OpenChamber maintenance when idle
      DefaultDependencies=no
      After=openchamber-bootstrap.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-tool-update-restart.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-retry-guard.service <<'EOF'
      [Unit]
      Description=Bound repeated OpenCode provider retries
      DefaultDependencies=no
      After=openchamber-web.service
      Wants=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Service]
      Type=oneshot
      Environment=PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin
      ExecStart=${openchamberRetryGuard}/bin/openchamber-retry-guard
      StandardOutput=append:/home/openchamber/.config/openchamber/logs/openchamber-retry-guard.log
      StandardError=append:/home/openchamber/.config/openchamber/logs/openchamber-retry-guard.log
      TasksMax=infinity
      EOF
      cat > etc/systemd/system/openchamber-retry-guard.timer <<'EOF'
      [Unit]
      Description=Periodic OpenCode provider retry guard
      DefaultDependencies=no
      After=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

      [Timer]
      OnBootSec=2m
      OnUnitActiveSec=1m
      Unit=openchamber-retry-guard.service

      [Install]
      WantedBy=multi-user.target
      EOF
      cat > etc/systemd/system/openchamber-web-monitor.service <<'EOF'
      [Unit]
      Description=Monitor OpenChamber web and managed OpenCode
      DefaultDependencies=no
      After=openchamber-web.service
      Wants=openchamber-web.service
      Conflicts=shutdown.target
      Before=shutdown.target

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
      Conflicts=shutdown.target
      Before=shutdown.target

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
      Wants=openchamber-container-setup.service nix-daemon.socket nix-daemon.service user@3000.service dockerd.service openchamber-bootstrap.service openchamber-web.service openchamber-tool-auto-update.timer openchamber-tool-update-restart.timer openchamber-retry-guard.timer openchamber-web-monitor.timer
      After=openchamber-container-setup.service nix-daemon.socket user@3000.service dockerd.service
      AllowIsolate=yes
      EOF
      rm -f etc/systemd/system/docker.service \
        etc/systemd/system/docker.socket \
        etc/systemd/system/multi-user.target.wants/docker.service \
        etc/systemd/system/sockets.target.wants/docker.socket
      ln -s multi-user.target etc/systemd/system/default.target
      ln -s ../openchamber-container-setup.service etc/systemd/system/multi-user.target.wants/openchamber-container-setup.service
      ln -s ../nix-daemon.socket etc/systemd/system/multi-user.target.wants/nix-daemon.socket
      ln -s ../nix-daemon.service etc/systemd/system/multi-user.target.wants/nix-daemon.service
      ln -s ../user@.service etc/systemd/system/multi-user.target.wants/user@3000.service
      ln -s ../dockerd.service etc/systemd/system/multi-user.target.wants/dockerd.service
      ln -s ../openchamber-bootstrap.service etc/systemd/system/multi-user.target.wants/openchamber-bootstrap.service
      ln -s ../openchamber-web.service etc/systemd/system/multi-user.target.wants/openchamber-web.service
      ln -s ../openchamber-tool-auto-update.timer etc/systemd/system/multi-user.target.wants/openchamber-tool-auto-update.timer
      ln -s ../openchamber-tool-update-restart.timer etc/systemd/system/multi-user.target.wants/openchamber-tool-update-restart.timer
      ln -s ../openchamber-retry-guard.timer etc/systemd/system/multi-user.target.wants/openchamber-retry-guard.timer
      ln -s ../openchamber-web-monitor.timer etc/systemd/system/multi-user.target.wants/openchamber-web-monitor.timer
    '';
    fakeRootCommands = ''
      chown -R root:root nix/store nix/var/log/nix nix/var/nix
      chmod -R u+rwX,go+rX nix/store nix/var/log/nix nix/var/nix
      chown 0:0 usr/bin/sudo
      chmod 4755 usr/bin/sudo
    '';
    config = {
      Cmd = [ "${openchamberEntrypoint}/bin/openchamber-systemd-entrypoint" ];
      Env = [
        "HOME=/home/openchamber"
        "USER=openchamber"
        "DOCKER_HOST=unix:///var/run/docker.sock"
        "XDG_RUNTIME_DIR=/run/user/3000"
        "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/3000/bus"
        "XDG_CONFIG_HOME=/home/openchamber/.config"
        "XDG_STATE_HOME=/home/openchamber/.local/state"
        "XDG_CACHE_HOME=/home/openchamber/.cache"
        "XDG_DATA_HOME=/home/openchamber/.local/share"
        "NPM_CONFIG_PREFIX=/home/openchamber/.local/share/openchamber-tools/npm"
        "npm_config_prefix=/home/openchamber/.local/share/openchamber-tools/npm"
        "OPENCODE_AUTOMATION_DIR=/home/openchamber/.automation"
        "PATH=/home/openchamber/.local/bin:/home/openchamber/.local/share/openchamber-tools/npm/bin:${openchamberPath}:/bin:/usr/bin"
        "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
        "NIX_CONFIG=experimental-features = nix-command flakes"
        "NIX_REMOTE=daemon"
        "OPENCHAMBER_ALLOW_UNAUTHENTICATED_LAN=true"
      ];
      WorkingDir = "/home/openchamber";
      ExposedPorts = {
        "3000/tcp" = { };
      };
    };
  };

  openchamberDeploymentId = builtins.hashString "sha256" (toString openchamberImage);
  openchamberDeployQueued = pkgs.writeShellScriptBin "openchamber-deploy-queued" ''
    set -eu

    state_dir=${openchamberDeploymentState}
    desired_file="$state_dir/desired"
    applied_file="$state_dir/applied"
    applying_file="$state_dir/applying"
    failed_file="$state_dir/failed"
    audit_log=${openchamberHome}/.config/openchamber/logs/restart-audit.log

    install -d -m 0755 "$state_dir"
    install -d -m 0755 -o 3000 -g 3000 "$(dirname "$audit_log")"
    [ -f "$desired_file" ] || exit 0

    desired="$(cat "$desired_file")"
    applied=""
    failed=""
    [ ! -f "$applied_file" ] || applied="$(cat "$applied_file")"
    [ ! -f "$failed_file" ] || failed="$(cat "$failed_file")"
    if [ "$desired" = "$applied" ]; then
      rm -f "$applying_file" "$failed_file"
      exit 0
    fi
    [ "$desired" != "$failed" ] || exit 0

    log_info() {
      message="$1"
      printf '%s info: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$message"
      printf '%s source=host-deployment %s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$message" >> "$audit_log"
    }

    mark_failed() {
      printf '%s\n' "$desired" > "$failed_file.tmp"
      mv "$failed_file.tmp" "$failed_file"
      rm -f "$applying_file"
    }

    if ! ${pkgs.systemd}/bin/systemctl show podman-openchamber.service \
      --property=Environment --value \
      | ${pkgs.gnugrep}/bin/grep -Fq \
        "GHOSTSHIP_OPENCHAMBER_DEPLOYMENT_ID=$desired"; then
      log_info "action=defer desired=$desired reason=unit-not-reloaded"
      exit 0
    fi

    printf '%s\n' "$desired" > "$applying_file.tmp"
    mv "$applying_file.tmp" "$applying_file"
    log_info "action=restart-container desired=$desired"
    if ! ${pkgs.systemd}/bin/systemctl restart podman-openchamber.service; then
      mark_failed
      log_info "action=deployment-failed desired=$desired reason=container-restart"
      exit 1
    fi

    healthy=0
    for _ in $(seq 1 120); do
      if [ "$(${pkgs.podman}/bin/podman inspect openchamber \
        --format '{{.State.Health.Status}}' 2>/dev/null || true)" = "healthy" ] \
        && ${pkgs.podman}/bin/podman exec openchamber \
          systemctl is-active --quiet openchamber-web.service \
        && ${pkgs.podman}/bin/podman exec openchamber \
          curl -fsS --max-time 5 http://127.0.0.1:3000/ >/dev/null 2>&1; then
        healthy=1
        break
      fi
      sleep 10
    done

    if [ "$healthy" -ne 1 ]; then
      mark_failed
      log_info "action=deployment-failed desired=$desired reason=health-timeout"
      exit 1
    fi

    running="$(${pkgs.podman}/bin/podman inspect openchamber \
      --format '{{index .Config.Labels "io.ghostship.openchamber.deployment"}}' \
      2>/dev/null || true)"
    if [ "$running" != "$desired" ]; then
      mark_failed
      log_info "action=deployment-failed desired=$desired reason=image-identity-mismatch running=$running"
      exit 1
    fi

    printf '%s\n' "$desired" > "$applied_file.tmp"
    mv "$applied_file.tmp" "$applied_file"
    rm -f "$applying_file" "$failed_file"
    log_info "action=deployment-complete desired=$desired"
  '';

in
{
  virtualisation.oci-containers.containers."openchamber" = {
    image = "${imageName}:${imageTag}";
    imageFile = openchamberImage;
    pull = "never";
    labels = {
      "io.containers.autoupdate" = "disabled";
      "io.ghostship.openchamber.deployment" = openchamberDeploymentId;
    };
    ports = [ ];
    extraOptions = [
      "--privileged"
      "--systemd=always"
      "--pids-limit=-1"
      "--stop-timeout=180"
      "--network=ghostship_net"
      "--health-cmd=${openchamberContainerHealth}/bin/openchamber-container-health"
      "--health-interval=30s"
      "--health-timeout=15s"
      "--health-retries=5"
      "--health-start-period=5m"
      "--health-on-failure=kill"
    ];
    volumes = [
      "${openchamberDocker}:/var/lib/docker:rw"
      "${openchamberWorkspace}:/workspace:rw"
      "${openchamberHome}:/home/openchamber:rw"
      "${openchamberNixRoot}/nix:/nix:rw"
      "${openchamberSecrets}:${openchamberSecretsFile}:ro"
      "/mnt/share:/mnt/share:rw"
    ];
    environmentFiles = [ openchamberSecrets ];
  };

  systemd.tmpfiles.rules = [
    "d /srv/apps/openchamber 0755 root root -"
    "d ${openchamberDocker} 0755 root root -"
    "d ${openchamberHome} 0755 3000 3000 -"
    "d ${openchamberNixRoot} 0755 root root -"
    "d ${openchamberNixRoot}/nix 0755 root root -"
    "d ${openchamberWorkspace} 0755 3000 3000 -"
  ];

  system.activationScripts.openchamber-deployment = {
    text = ''
      install -d -m 0755 ${openchamberDeploymentState}
      printf '%s\n' ${lib.escapeShellArg openchamberDeploymentId} \
        > ${openchamberDeploymentState}/desired.tmp
      mv ${openchamberDeploymentState}/desired.tmp ${openchamberDeploymentState}/desired
    '';
    supportsDryActivation = false;
  };

  systemd.services.openchamber-deploy-when-idle = {
    # Retain the unit name so existing timers and deployment state converge.
    description = "Deploy an operator-approved OpenChamber image";
    after = [ "podman.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${openchamberDeployQueued}/bin/openchamber-deploy-queued";
      TimeoutStartSec = "25m";
    };
  };

  systemd.timers.openchamber-deploy-when-idle = {
    description = "Apply a queued operator-approved OpenChamber deployment";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2m";
      OnUnitActiveSec = "1m";
      Persistent = true;
      Unit = "openchamber-deploy-when-idle.service";
    };
  };

  systemd.services.podman-openchamber = {
    restartIfChanged = false;
    stopIfChanged = false;
    after = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    wants = [
      "init-ghostship-net.service"
      "mnt-share.mount"
    ];
    serviceConfig = {
      Environment = lib.mkForce [
        "PODMAN_SYSTEMD_UNIT=%n"
        "GHOSTSHIP_OPENCHAMBER_DEPLOYMENT_ID=${openchamberDeploymentId}"
      ];
      TimeoutStopSec = lib.mkForce "210s";
      SuccessExitStatus = [
        0
        130
      ];
    };
    preStart = lib.mkAfter ''
      set -eu

      install -d -m0755 -o root -g root /srv/apps/openchamber
      install -d -m0755 -o root -g root ${openchamberDocker}
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}
      install -d -m0755 -o root -g root ${openchamberNixRoot}
      install -d -m0755 -o 3000 -g 3000 ${openchamberWorkspace}

      nix_store_uri='local?root=${openchamberNixRoot}'
      ${pkgs.nix}/bin/nix copy \
        --no-check-sigs \
        --to "$nix_store_uri" \
        ${lib.escapeShellArgs (map toString openchamberImageContents)}

      gcroot_dir=${openchamberNixRoot}/nix/var/nix/gcroots/ghostship-openchamber-image
      rm -rf "$gcroot_dir"
      install -d -m0755 -o root -g root "$gcroot_dir"
      for store_path in ${lib.escapeShellArgs (map toString openchamberImageContents)}; do
        ln -s "$store_path" "$gcroot_dir/$(basename "$store_path")"
      done

      rm -f ${openchamberNixRoot}/nix/var/nix/temproots/*
      rm -rf ${openchamberNixRoot}/nix/var/nix/builds/*
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/bin
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/share
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.local/state
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.cache
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/openchamber
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/opencode
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.automation
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.config/systemd/user
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/bootstrap.d
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/before-openchamber.d
      install -d -m0755 -o 3000 -g 3000 ${openchamberHome}/.openchamber/hooks/doctor.d

      if [ -e ${openchamberHome}/.config/systemd/user/openchamber.service ] \
        && grep -q 'ExecStart=/home/openchamber/.local/bin/openchamber-web-run' ${openchamberHome}/.config/systemd/user/openchamber.service; then
        rm -f ${openchamberHome}/.config/systemd/user/openchamber.service
      fi
      if [ -e ${openchamberHome}/.config/systemd/user/default.target ] \
        && grep -q 'OpenChamber User Default Target' ${openchamberHome}/.config/systemd/user/default.target; then
        rm -f ${openchamberHome}/.config/systemd/user/default.target
      fi
      rm -f ${openchamberHome}/.config/systemd/user/default.target.wants/openchamber.service
    '';
  };
}
