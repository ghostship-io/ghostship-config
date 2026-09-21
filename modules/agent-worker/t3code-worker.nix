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

  antigravityAcp = pkgs.callPackage ../../packages/t3code/antigravity-acp.nix { };
  antigravityEntry = lib.optionalString cfg.enableAntigravity ''
    ,
        "antigravity": {"driver": "antigravity", "enabled": true, "config": {"binaryPath": "${antigravityAcp}/bin/agy_acp_server.par"}}
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
    export NODE_NO_WARNINGS=1
    export PATH=${lib.escapeShellArg t3WorkerPath}:$PATH
    unset LD_LIBRARY_PATH

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
    [ ! -f "$config_file" ] || exit 0
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

  # The existing ghostship-agent-maintenance.timer owns installing and
  # upgrading the CLIs. This watcher only restarts the worker when an installed
  # version changed since the worker last started, so the running server picks
  # up the new tools without a second maintenance run or an operator login.
  t3codeWorkerUpdate = pkgs.writeShellScriptBin "t3code-worker-update" ''
    set -eu
    state_file=${lib.escapeShellArg "${cfg.baseDir}/worker-tool-versions"}

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
      chown ${user}:${user} "$state_file" 2>/dev/null || true
      printf 'info: recorded initial worker tool versions\n'
      exit 0
    fi

    previous="$(cat "$state_file")"
    if [ "$current" != "$previous" ]; then
      printf 'info: agent tools changed; restarting t3code-worker.service\n'
      printf '%s\n' "$current" > "$state_file"
      chown ${user}:${user} "$state_file" 2>/dev/null || true
      exec ${pkgs.systemd}/bin/systemctl restart t3code-worker.service
    fi
    printf 'info: agent tools unchanged\n'
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

    users.users.${user}.linger = lib.mkDefault true;

    environment.systemPackages = lib.mkIf cfg.enableAntigravity [ antigravityAcp ];

    # Wait for the first CLI install so the worker does not restart-loop on a
    # fresh host. Maintenance is oneshot, so this only delays first start.
    systemd.services.t3code-worker = {
      description = "T3 Code worker environment";
      after = [
        "network-online.target"
        "ghostship-agent-maintenance.service"
      ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "simple";
        User = user;
        Group = user;
        WorkingDirectory = home;
        ExecStartPre = "${t3codeWorkerManagedConfig}/bin/t3code-worker-managed-config";
        ExecStart = "${t3codeWorkerRun}/bin/t3code-worker-run";
        Restart = "always";
        RestartSec = "5s";
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
  };
}
