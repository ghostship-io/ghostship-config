{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.t3Worker;
  user = cfg.user;
  home = config.users.users.${user}.home or "/home/${user}";
  uid = toString (config.users.users.${user}.uid or 1000);
  agentNpmPrefix = "${home}/.local/share/ghostship-agent-tools/npm";
  agentBinDir = "${agentNpmPrefix}/bin";
  runtimePath = lib.makeBinPath [
    pkgs.coreutils
    pkgs.git
    pkgs.gnugrep
    pkgs.openssh
    pkgs.curl
    pkgs.cloudflared
    pkgs.nodejs_24
    pkgs.python3
  ];
  t3WorkerPath = "${agentBinDir}:${home}/.local/bin:${runtimePath}:/run/current-system/sw/bin:/usr/bin:/bin";
  t3codeActivityProbe = pkgs.callPackage ../../packages/t3code/activity-probe/default.nix { };

  antigravityAcp = pkgs.callPackage ../../packages/t3code/antigravity-acp.nix { };
  antigravityEntry = lib.optionalString cfg.enableAntigravity ''
    ,
        "antigravity": {"driver": "antigravity", "enabled": true, "config": {"binaryPath": "agy_acp_server.par"}}
  '';

  # T3 discovers providers on the server's PATH. The develop role installs the
  # user-local npm CLIs; this wrapper only points T3 at them and pins the data
  # directory, host, and port.
  t3codeWorkerRun = pkgs.writeShellScriptBin "t3code-worker-run" ''
    set -eu
    export HOME=${lib.escapeShellArg home}
    export USER=${lib.escapeShellArg user}
    export T3CODE_HOME=${lib.escapeShellArg cfg.baseDir}
    export T3CODE_HOST=127.0.0.1
    export T3CODE_PORT=${toString cfg.port}
    export T3CODE_NO_BROWSER=true
    export T3CODE_NODE_EXECUTABLE=${pkgs.nodejs_24}/bin/node
    export NODE_OPTIONS="--require=${../../packages/t3code/t3-runtime-preload.cjs}"
    export NODE_NO_WARNINGS=1
    export PATH=${lib.escapeShellArg t3WorkerPath}:$PATH
    # Provider subprocesses inherit this environment. Some providers expect a
    # session runtime directory and D-Bus address; provide the worker's own.
    export XDG_RUNTIME_DIR=/run/user/${toString uid}
    if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
      export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
    fi
    # T3's downloaded native package and node-pty fallback need the Nix C++
    # runtime. T3 sanitizes provider child environments before launching them.
    export LD_LIBRARY_PATH=${lib.escapeShellArg (lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ])}

    if [ ! -x ${lib.escapeShellArg "${agentBinDir}/t3"} ]; then
      printf 'error: t3 is not installed yet; run ghostship-agent-maintenance\n' >&2
      exit 1
    fi

    exec ${lib.escapeShellArg "${agentBinDir}/t3"} serve \
      --host "$T3CODE_HOST" \
      --port "$T3CODE_PORT" \
      --base-dir "$T3CODE_HOME" \
      ${lib.escapeShellArg home}
  '';

  # Seed provider instances only when the user has no settings yet, matching the
  # container's managed-config contract. Existing user settings are preserved.
  t3codeWorkerManagedConfig = pkgs.writeShellScriptBin "t3code-worker-managed-config" ''
    set -eu
    config_dir=${lib.escapeShellArg cfg.baseDir}/userdata
    config_file="$config_dir/settings.json"
    if [ -f "$config_file" ]; then
      # Older managed settings captured the build's immutable store path. That
      # path becomes stale after an upgrade and garbage collection. Migrate
      # only that known generated value; leave every other user setting alone.
      antigravity_path="$(${pkgs.jq}/bin/jq -r \
        '.providerInstances.antigravity.config.binaryPath // empty' \
        "$config_file" 2>/dev/null || true)"
      case "${lib.boolToString cfg.enableAntigravity}:$antigravity_path" in
        true:/nix/store/*-antigravity-acp-*/bin/agy_acp_server.par)
          tmp="$(mktemp "$config_dir/settings.json.tmp.XXXXXX")"
          trap 'rm -f "$tmp"' EXIT
          ${pkgs.jq}/bin/jq \
            '.providerInstances.antigravity.config.binaryPath = "agy_acp_server.par"' \
            "$config_file" > "$tmp"
          chmod 0600 "$tmp"
          chown ${user}:${user} "$tmp"
          mv "$tmp" "$config_file"
          trap - EXIT
          ;;
      esac
      exit 0
    fi
    mkdir -p "$config_dir"
    tmp="$(mktemp "$config_dir/settings.json.tmp.XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    cat > "$tmp" <<'JSON'
    {
      "providerInstances": {
        "codex": {"driver": "codex", "enabled": true, "config": {"binaryPath": "codex"}},
        "opencode": {"driver": "opencode", "enabled": true, "config": {"binaryPath": "opencode"}},
        "claude": {"driver": "claude", "enabled": true, "config": {"binaryPath": "claude"}},
        "cursor": {"driver": "cursor", "enabled": true, "config": {"binaryPath": "cursor"}},
        "grok": {"driver": "grok", "enabled": true, "config": {"binaryPath": "grok"}}${antigravityEntry}
      }
    }
    JSON
    chmod 0600 "$tmp"
    mv "$tmp" "$config_file"
    chown ${user}:${user} "$config_file"
  '';

  # Runs as root so it can trigger the system maintenance unit. Version probes
  # run as the worker user so they never create root-owned provider state.
  versionOf = tool: ''
    if [ -x ${lib.escapeShellArg "${agentBinDir}/${tool}"} ]; then
      ${pkgs.util-linux}/bin/runuser -u ${user} -- ${lib.escapeShellArg "${agentBinDir}/${tool}"} --version 2>/dev/null | head -n 1 || true
    fi
  '';

  # The existing develop-role ghostship-agent-maintenance.timer owns installing
  # and upgrading the CLIs. This watcher only restarts the worker when an
  # installed version changed since the worker last started, so the running
  # server picks up the new tools without a second maintenance run or an
  # operator login.
  t3codeWorkerUpdate = pkgs.writeShellScriptBin "t3code-worker-update" ''
    set -eu
    state_file=/var/lib/t3code-worker-health/tool-versions

    current="$(
      printf 't3=%s\n' "$(${versionOf "t3"})"
      printf 'codex=%s\n' "$(${versionOf "codex"})"
      printf 'opencode=%s\n' "$(${versionOf "opencode"})"
      printf 'claude=%s\n' "$(${versionOf "claude"})"
      printf 'cursor=%s\n' "$(${versionOf "cursor"})"
      printf 'grok=%s\n' "$(${versionOf "grok"})"
    )"

    if [ ! -f "$state_file" ]; then
      printf '%s\n' "$current" > "$state_file"
      printf 'info: recorded initial worker tool versions\n'
      exit 0
    fi

    previous="$(cat "$state_file")"
    if [ "$current" != "$previous" ]; then
      pending_restart=/var/lib/t3code-worker-health/tool-restart.pending
      printf '%s\n' "$current" > "$state_file"
      printf '%s\n' "$current" > "$pending_restart"
      printf 'info: agent tools changed; queued restart until the worker is idle\n'
      exit 0
    fi
    printf 'info: agent tools unchanged\n'
  '';

  # Recover a stopped worker immediately and a wedged but still-running worker
  # only after three consecutive failed probes. Never interrupt active or
  # unknown agent work. The Cloudflare connector is independent and can be
  # restarted safely without restarting the worker.
  t3codeWorkerHealth = pkgs.writeShellScriptBin "t3code-worker-health" ''
    set -eu
    state_dir=/var/lib/t3code-worker-health
    log_file="$state_dir/health.log"
    mkdir -p "$state_dir"

    log_info() {
      printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$log_file"
    }
    increment() {
      file="$state_dir/$1.failures"
      count=0
      previous_time=0
      if [ -f "$file" ]; then read -r count previous_time < "$file" || count=0; fi
      [ -n "$count" ] || count=0
      case "$count" in *[!0-9]*) count=0 ;; esac
      [ -n "$previous_time" ] || previous_time=0
      case "$previous_time" in *[!0-9]*) previous_time=0 ;; esac
      now="$(date +%s)"
      if [ "$now" -lt "$previous_time" ] || [ "$((now - previous_time))" -gt 300 ]; then
        count=0
      fi
      count=$((count + 1))
      printf '%s %s\n' "$count" "$now" > "$file"
      printf '%s\n' "$count"
    }
    reset_streak() { rm -f "$state_dir/$1.failures"; }
    worker_idle() {
      ${pkgs.util-linux}/bin/runuser -u ${user} -- env \
        HOME=${lib.escapeShellArg home} \
        T3CODE_HOME=${lib.escapeShellArg cfg.baseDir} \
        ${t3codeActivityProbe}/bin/t3code-activity-probe
    }

    exec 9>"$state_dir/health.lock"
    ${pkgs.util-linux}/bin/flock -n 9 || exit 0

    if ! ${pkgs.systemd}/bin/systemctl is-active --quiet t3code-worker.service; then
      log_info "worker is stopped; starting it"
      ${pkgs.systemd}/bin/systemctl reset-failed t3code-worker.service || true
      ${pkgs.systemd}/bin/systemctl start t3code-worker.service
      reset_streak worker
    elif ${pkgs.curl}/bin/curl -fsS --max-time 5 \
      http://127.0.0.1:${toString cfg.port}/ >/dev/null; then
      reset_streak worker
    else
      failures="$(increment worker)"
      log_info "worker HTTP probe failed ($failures/3)"
      if [ "$failures" -ge 3 ]; then
        if worker_idle; then
          # Recheck at the recovery boundary so a newly-started turn wins.
          sleep 5
          if worker_idle; then
            log_info "worker remained unhealthy and is idle; restarting it"
            ${pkgs.systemd}/bin/systemctl restart t3code-worker.service
            reset_streak worker
          fi
        else
          status=$?
          if [ "$status" -eq 1 ]; then
            log_info "worker has active work; restart deferred"
          else
            log_info "worker activity is unknown; restart deferred"
          fi
        fi
      fi
    fi

    pending_restart="$state_dir/tool-restart.pending"
    if [ -f "$pending_restart" ]; then
      if worker_idle; then
        sleep 5
        if [ -f "$pending_restart" ] && worker_idle; then
          log_info "worker is idle; applying queued tool-update restart"
          ${pkgs.systemd}/bin/systemctl restart t3code-worker.service
          rm -f "$pending_restart"
        fi
      else
        status=$?
        if [ "$status" -eq 1 ]; then
          log_info "tool-update restart is queued; active work is preserved"
        else
          log_info "tool-update restart is queued; activity is unknown"
        fi
      fi
    fi

    ${lib.optionalString cfg.directTunnel.enable ''
      if [ ! -s ${lib.escapeShellArg cfg.directTunnel.tokenFile} ]; then
        log_info "Cloudflare tunnel token is missing"
        exit 0
      fi
      if ! ${pkgs.systemd}/bin/systemctl is-active --quiet t3code-worker-cloudflare.service; then
        log_info "Cloudflare connector is stopped; starting it"
        ${pkgs.systemd}/bin/systemctl reset-failed t3code-worker-cloudflare.service || true
        ${pkgs.systemd}/bin/systemctl start t3code-worker-cloudflare.service
        reset_streak tunnel
        exit 0
      fi

      public_headers="$state_dir/public.headers"
      public_status="$(${pkgs.curl}/bin/curl -sS --max-time 10 -o /dev/null \
        -D "$public_headers" -w '%{http_code}' \
        ${lib.escapeShellArg "https://${cfg.directTunnel.hostname}/"} || true)"
      public_route_ready=false
      case "$public_status" in
        3??)
          # An unauthenticated probe of an Access-protected application must
          # be the Cloudflare Access login challenge, not an arbitrary edge
          # redirect or a missing-ingress response.
          if ${pkgs.gnugrep}/bin/grep -Eqi \
            '^location: https://[^/]+\.cloudflareaccess\.com/cdn-cgi/access/login/' \
            "$public_headers"; then
            public_route_ready=true
          fi
          ;;
      esac
      if ${pkgs.curl}/bin/curl -fsS --max-time 5 \
        http://127.0.0.1:45679/ready >/dev/null \
        && "$public_route_ready"; then
        reset_streak tunnel
      else
        failures="$(increment tunnel)"
        log_info "Cloudflare connector or public route failed (HTTP ''${public_status:-000}, $failures/3)"
        if [ "$failures" -ge 3 ]; then
          log_info "Cloudflare connector remained unavailable; restarting it"
          ${pkgs.systemd}/bin/systemctl restart t3code-worker-cloudflare.service
          reset_streak tunnel
        fi
      fi
    ''}
  '';

in
{
  config = lib.mkIf cfg.enable {
    # The Antigravity ACP archive is unfree; scope the exception to this app.
    nixpkgs.config.allowUnfreePredicate =
      pkg:
      builtins.elem (lib.getName pkg) [
        "antigravity-acp"
      ];

    # Enable the user manager across login sessions so the worker user's own
    # `systemctl --user` tooling and any `t3 service` use survive logout. The
    # worker server itself is a system unit, matching the Docker T3 container.
    users.users.${user}.linger = lib.mkDefault true;

    environment.systemPackages = lib.mkIf cfg.enableAntigravity [ antigravityAcp ];

    # Wait for the first CLI install so the worker does not restart-loop on a
    # fresh host. Maintenance is oneshot, so this only delays first start.
    systemd.services.t3code-worker = {
      description = "T3 Code worker environment";
      restartIfChanged = false;
      stopIfChanged = false;
      after = [
        "network-online.target"
        "ghostship-agent-maintenance.service"
      ];
      wants = [
        "network-online.target"
        "ghostship-agent-maintenance.service"
      ];
      serviceConfig = {
        Type = "simple";
        User = user;
        Group = user;
        WorkingDirectory = home;
        ExecStartPre = "${t3codeWorkerManagedConfig}/bin/t3code-worker-managed-config";
        ExecStart = "${t3codeWorkerRun}/bin/t3code-worker-run";
        Restart = "always";
        RestartSec = "5s";
        # `t3 serve` prints a one-time pairing credential and QR code to stdout.
        # Keep errors in the journal without persisting that bootstrap secret.
        StandardOutput = "null";
        StandardError = "journal";
        # Provider sessions and their tools run in this cgroup.
        KillMode = "mixed";
        TimeoutStopSec = "60s";
        OOMPolicy = "continue";
      };
      wantedBy = [ "multi-user.target" ];
    };

    systemd.services.t3code-worker-update = {
      description = "Update T3 Code and provider CLIs for the worker";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "t3code-worker-health";
        StateDirectoryMode = "0700";
        WorkingDirectory = home;
        TimeoutStartSec = "30m";
        ExecStart = "${t3codeWorkerUpdate}/bin/t3code-worker-update";
      };
    };

    systemd.timers.t3code-worker-update = {
      description = "Refresh T3 Code worker and provider CLIs every 4 hours";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "10m";
        OnUnitActiveSec = "4h";
        Persistent = true;
        Unit = "t3code-worker-update.service";
      };
    };

    assertions = [
      {
        assertion = builtins.hasAttr "ghostship-agent-maintenance" config.systemd.services;
        message = "ghostship.t3Worker requires the develop module that provides ghostship-agent-maintenance.";
      }
    ] ++ lib.optional cfg.directTunnel.enable {
        assertion = cfg.directTunnel.hostname != "";
        message = "ghostship.t3Worker.directTunnel.hostname must be set when the direct tunnel is enabled.";
      };

    systemd.services.t3code-worker-cloudflare = lib.mkIf cfg.directTunnel.enable {
      description = "Dedicated Cloudflare tunnel for the T3 Code worker";
      after = [
        "network-online.target"
        "t3code-worker.service"
      ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "simple";
        User = user;
        Group = user;
        ExecStart = "${pkgs.cloudflared}/bin/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:45679 run --token-file ${cfg.directTunnel.tokenFile}";
        Restart = "always";
        RestartSec = "5s";
      };
      unitConfig.ConditionPathExists = cfg.directTunnel.tokenFile;
      wantedBy = [ "multi-user.target" ];
    };

    systemd.services.t3code-worker-health = {
      description = "Repair the T3 Code worker and apply idle maintenance";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "t3code-worker-health";
        StateDirectoryMode = "0700";
        ExecStart = "${t3codeWorkerHealth}/bin/t3code-worker-health";
      };
    };

    systemd.timers.t3code-worker-health = {
      description = "Continuously verify the T3 Code worker";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "1m";
        OnUnitActiveSec = "2m";
        Persistent = true;
        Unit = "t3code-worker-health.service";
      };
    };

  };
}
