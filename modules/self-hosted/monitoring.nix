{
  config,
  lib,
  pkgs,
  ...
}:
let
  secrets = config.ghostship.selfHostedSecrets.projections.monitoring.path;
  python = pkgs.python3.withPackages (ps: [
    ps.python-socketio
    ps.requests
    ps.websocket-client
  ]);
  provision = pkgs.writeShellScriptBin "ghostship-monitoring-provision" ''
    set -euo pipefail
    set -a
    . ${secrets}
    set +a
    export KUMA_URL="http://$(${pkgs.podman}/bin/podman inspect uptime-kuma --format '{{(index .NetworkSettings.Networks "ghostship_net").IPAddress}}'):3001"
    exec ${python}/bin/python ${./monitoring-provision.py} ${config.ghostship.appRegistryFile}
  '';
  # The single host publisher for the three topics (security, operations,
  # informational); see ghostship-notify.py for the priority and tag rules.
  notify = pkgs.writeTextFile {
    name = "ghostship-notify";
    destination = "/bin/ghostship-notify";
    executable = true;
    text =
      "#!${pkgs.python3}/bin/python3\n"
      +
        builtins.replaceStrings
          [ "@secrets@" "@podman@" "@incidents@" ]
          [
            secrets
            "${pkgs.podman}/bin/podman"
            (if config.ghostship.notify.incidentSpool == null then "" else config.ghostship.notify.incidentSpool)
          ]
          (builtins.readFile ./ghostship-notify.py);
  };
  # Unit outcomes for ghostship-failure@ and ghostship-success@. A failure goes
  # to operations; a success summary goes silently to informational and quotes
  # only restic summary lines, so it never forwards arbitrary journal output.
  unitNotify = pkgs.writeShellApplication {
    name = "ghostship-unit-notify";
    runtimeInputs = [
      pkgs.systemd
      pkgs.gnugrep
      pkgs.coreutils
      notify
    ];
    text = ''
      outcome=$1
      unit=$2
      host=${config.networking.hostName}
      description=$(systemctl show -P Description "$unit")
      case $outcome in
        failure)
          result=$(systemctl show -P Result "$unit")
          status=$(systemctl show -P ExecMainStatus "$unit")
          exec ghostship-notify --topic operations --priority 4 --source systemd --incident \
            --dedupe "$unit" --title "Service $unit failed on $host" \
            "$description: $result (exit status $status). Inspect: journalctl -b -u $unit"
          ;;
        success)
          invocation=$(systemctl show -P InvocationID "$unit")
          if [ -n "$invocation" ]; then
            log=$(journalctl -o cat --no-pager "_SYSTEMD_INVOCATION_ID=$invocation")
          else
            log=$(journalctl -o cat --no-pager -n 200 -u "$unit")
          fi
          summary=$(grep -E '^(Added to the repository|processed |snapshot [0-9a-f]+ saved|keep [0-9]+ snapshots|remove [0-9]+ snapshots|no errors were found|this removes|unused size after prune)' <<<"$log" | tail -n 8 || true)
          exec ghostship-notify --topic informational --priority 2 --source systemd \
            --state resolved --dedupe "$unit" --title "$description succeeded on $host" \
            "''${summary:-$unit finished without a summary.}"
          ;;
        *)
          echo "Usage: ghostship-unit-notify failure|success UNIT" >&2
          exit 2
          ;;
      esac
    '';
  };
in
{
  options.ghostship.notify.package = lib.mkOption {
    type = lib.types.package;
    readOnly = true;
    default = notify;
    description = "ghostship-notify, the host's ntfy publisher; run it as root.";
  };
  options.ghostship.notify.incidentSpool = lib.mkOption {
    type = lib.types.nullOr lib.types.str;
    default = null;
    description = "Root-owned directory where --incident alerts are queued for the GitHub coordinator's repair threads.";
  };
  config = {
    environment.systemPackages = [
      provision
      notify
    ];
    ghostship.apps.uptime-kuma = {
      name = "Uptime Kuma";
      group = "Infrastructure";
      description = "Service Monitoring";
      icon = "sh-uptime-kuma";
      order = 180;
      hostname = "uptime.ghostship.io";
      origin = "http://muximux:80";
      muximux = {
        icon = "fa-heartbeat";
      };
    };
    ghostship.apps.ntfy = {
      apparmorProfile = "ghostship-ntfy";
      healthPath = "/v1/health";
      name = "ntfy";
      group = "Infrastructure";
      description = "Android Notifications";
      icon = "sh-ntfy";
      order = 190;
      hostname = "ntfy.ghostship.io";
      origin = "http://ntfy:8080";
      muximux = {
        icon = "fa-bell";
      };
    };

    virtualisation.oci-containers.containers = {
      uptime-kuma = {
        podman.sdnotify = "healthy";
        image = "docker.io/louislam/uptime-kuma:2";
        pull = "always";
        labels."io.containers.autoupdate" = "registry";
        user = "3000:3000";
        environment = {
          UPTIME_KUMA_DB_TYPE = "sqlite";
          TZ = "Pacific/Honolulu";
        };
        volumes = [ "/srv/apps/uptime-kuma:/app/data:rw" ];
        extraOptions = [
          "--network=ghostship_net"
          "--health-cmd=node extra/healthcheck.js"
          "--health-interval=30s"
          "--health-timeout=10s"
          "--health-retries=5"
          "--health-start-period=2m"
          "--health-on-failure=kill"
        ];
      };
      ntfy = {
        podman.sdnotify = "healthy";
        image = "docker.io/binwiederhier/ntfy:latest";
        pull = "always";
        labels."io.containers.autoupdate" = "registry";
        user = "3000:3000";
        cmd = [ "serve" ];
        volumes = [
          "/srv/apps/ntfy:/var/lib/ntfy:rw"
          "/run/ghostship-ntfy:/etc/ntfy:ro"
        ];
        extraOptions = [
          "--network=ghostship_net"
          "--health-cmd=wget -q -O /dev/null http://127.0.0.1:8080/v1/health"
          "--health-interval=30s"
          "--health-timeout=10s"
          "--health-retries=5"
          "--health-start-period=30s"
          "--health-on-failure=kill"
        ];
      };
    };
    systemd.tmpfiles.rules = [
      "d /var/lib/ghostship-monitoring 0700 root root -"
      "d /srv/apps/uptime-kuma 0700 apps apps -"
      "d /srv/apps/ntfy 0700 apps apps -"
      "d /run/ghostship-ntfy 0750 root apps -"
      "d /var/lib/ghostship-notify 0700 root root -"
    ];
    systemd.services.podman-ntfy.preStart = ''
      set -euo pipefail
      . ${secrets}
      : "''${NTFY_ADMIN_HASH:?}" "''${NTFY_PUBLISH_HASH:?}" "''${NTFY_READER_HASH:?}"
      umask 077
      cat > /run/ghostship-ntfy/server.yml.new <<EOF
      base-url: https://ntfy.ghostship.io
      listen-http: ':8080'
      behind-proxy: true
      auth-file: /var/lib/ntfy/auth.db
      auth-default-access: deny-all
      enable-login: true
      enable-signup: false
      cache-file: /var/lib/ntfy/cache.db
      cache-duration: 72h
      auth-users:
        - 'the owner:$NTFY_ADMIN_HASH:admin'
        - 'publisher:$NTFY_PUBLISH_HASH:user'
        - 'android:$NTFY_READER_HASH:user'
      auth-access:
        - 'publisher:security:write-only'
        - 'publisher:operations:write-only'
        - 'publisher:informational:write-only'
        - 'android:security:read-only'
        - 'android:operations:read-only'
        - 'android:informational:read-only'
      EOF
      chown root:apps /run/ghostship-ntfy/server.yml.new
      chmod 640 /run/ghostship-ntfy/server.yml.new
      mv /run/ghostship-ntfy/server.yml.new /run/ghostship-ntfy/server.yml
    '';
    systemd.services.ghostship-monitoring-provision = {
      description = "Provision Ghostship monitors without overwriting user settings";
      requires = [
        "podman-uptime-kuma.service"
        "podman-ntfy.service"
      ];
      after = [
        "podman-uptime-kuma.service"
        "podman-ntfy.service"
      ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${provision}/bin/ghostship-monitoring-provision";
        TimeoutStartSec = "3min";
        UMask = "0077";
      };
    };
    # Attached centrally by notify-coverage.nix: failures to every covered unit,
    # summaries to the backup jobs.
    systemd.services."ghostship-failure@" = {
      description = "Notify about failed Ghostship service %i";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${unitNotify}/bin/ghostship-unit-notify failure %i";
      };
    };
    systemd.services."ghostship-success@" = {
      description = "Publish the routine summary of Ghostship service %i";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${unitNotify}/bin/ghostship-unit-notify success %i";
      };
    };
    systemd.services.ghostship-monitoring-heartbeats = {
      after = [ "ghostship-monitoring-provision.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.python3}/bin/python ${./monitoring-heartbeats.py}";
        TimeoutStartSec = "1min";
      };
      path = [ pkgs.podman ];
      unitConfig.ConditionPathExists = "/var/lib/ghostship-monitoring/push.json";
    };
    systemd.timers.ghostship-monitoring-heartbeats = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5min";
        OnUnitActiveSec = "5min";
      };
    };
    # The release this system was built from, for update notices.
    environment.etc."ghostship-version".text = lib.fileContents ../../VERSION;
    # A nightly upgrade that changed the running system posts the new release;
    # a failed one reaches operations and an incident through ghostship-failure@.
    systemd.services.nixos-upgrade = lib.mkIf config.system.autoUpgrade.enable {
      preStart = "${pkgs.coreutils}/bin/readlink -f /run/current-system > /run/ghostship-upgrade-before";
      postStart = ''
        before=$(${pkgs.coreutils}/bin/cat /run/ghostship-upgrade-before 2>/dev/null || true)
        after=$(${pkgs.coreutils}/bin/readlink -f /run/current-system)
        if [ "$before" != "$after" ]; then
          ${notify}/bin/ghostship-notify --topic informational --priority 2 --source updates \
            --state resolved --title "${config.networking.hostName} upgraded to $(${pkgs.coreutils}/bin/cat /etc/ghostship-version)" \
            "Nightly upgrade from main activated ''${after#/nix/store/}." || true
        fi
      '';
    };
    systemd.services.podman-auto-update.postStart = ''
      ${pkgs.coreutils}/bin/install -d -m0700 /var/lib/ghostship-monitoring
      ${pkgs.coreutils}/bin/date +%s > /var/lib/ghostship-monitoring/last-update-success
    '';
  };
}
