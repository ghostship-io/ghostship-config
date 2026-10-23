# SIEM alerting: two vmalert instances evaluate siem/rules against the stores,
# and the native ghostship-siem-alerts bridge delivers firing alerts to ntfy
# and, for high and critical ones, to the security campaign's T3 thread. vmalert sends
# nothing itself (blackhole notifier); the bridge polls its loopback API, so
# no service can push alerts in.
{ config, lib, pkgs, inputs, ... }:
let
  network = "ghostship_siem_net";
  uid = "3100";
  stateDir = "/var/lib/ghostship-siem-alerts";
  tokenDir = "/run/ghostship-siem-alerts";
  # The campaign thread (#102) that investigates and tunes (user decision 2026-10-21).
  campaignThread = "ed27de17-dd6b-4604-9069-87a321a5ad79";
  vmalert = { rules, port, datasource, extra ? [ ] }: {
    image = "docker.io/victoriametrics/vmalert@sha256:aafb962b5a5713c71f0d697d629416f9cccf23aecb74f0ec5e829ddbf3f221f2";
    user = "${uid}:${uid}";
    ports = [ "127.0.0.1:${toString port}:8880" ];
    volumes = [ "${./rules}:/rules:ro" ];
    extraOptions = [ "--network=${network}" ];
    cmd = [
      "-rule=/rules/${rules}"
      "-datasource.url=${datasource}"
      "-notifier.blackhole"
      # Alert state survives restarts, and ALERTS series are queryable.
      "-remoteWrite.url=http://victoriametrics:8428"
      "-remoteRead.url=http://victoriametrics:8428"
      "-httpListenAddr=:8880"
    ] ++ extra;
  };
  bridgeConfig = pkgs.writeText "ghostship-siem-alerts.json" (builtins.toJSON {
    sources = {
      logs = "http://127.0.0.1:8880";
      metrics = "http://127.0.0.1:8881";
    };
    state = "${stateDir}/state.json";
    suppressions = "${./suppressions.json}";
    notify = "${config.ghostship.notify.package}/bin/ghostship-notify";
    host = config.networking.hostName;
    ntfy_renotify = 6 * 3600;
    # Resolved from ghostship-podman-snapshot's metadata: ghostship-notify's own
    # lookup runs the Podman CLI, and this sandbox has no Podman API access.
    ntfy_container = "ntfy";
    ntfy_network = "ghostship_net";
    ntfy_port = 8080;
    t3_thread_id = campaignThread;
    t3_token_file = "${tokenDir}/t3-token";
    t3_container = "t3code";
    t3_network = "ghostship_net";
    t3_port = 3773;
    t3_renotify = 86400;
    t3_min_interval = 600;
    t3_daily_limit = 12;
    # Liveness and delivery metrics, read by node_exporter and the watchdog
    # (security-monitoring.nix). Same textfile directory as collection.nix.
    metrics = "/var/lib/ghostship-container-metrics/siem-bridge.prom";
  });
  python = pkgs.python3.withPackages (ps: [ ps.websockets ]);
  bridge = pkgs.writeShellApplication {
    name = "ghostship-siem-alerts";
    text = ''
      PYTHONPATH=${inputs.ghostship-private-agent}/tools/python \
        exec ${python}/bin/python3 ${./alerts.py} --config ${bridgeConfig} "$@"
    '';
  };
in
{
  ghostship.apps.vmalert-logs = {
    name = "vmalert (logs)";
    group = "Infrastructure";
    description = "SIEM log detections";
    icon = "sh-victoriametrics";
    order = 262;
  };
  ghostship.apps.vmalert-metrics = {
    name = "vmalert (metrics)";
    group = "Infrastructure";
    description = "SIEM metric detections";
    icon = "sh-victoriametrics";
    order = 263;
  };

  virtualisation.oci-containers.containers = {
    vmalert-logs = vmalert {
      rules = "logs.yml";
      port = 8880;
      datasource = "http://victorialogs:9428";
      # VictoriaLogs has no ingestion delay to wait for beyond Vector's batching.
      extra = [ "-rule.defaultRuleType=vlogs" "-rule.evalDelay=30s" ];
    };
    vmalert-metrics = vmalert {
      rules = "metrics.yml";
      port = 8881;
      datasource = "http://victoriametrics:8428";
    };
  };

  systemd.services = lib.genAttrs [ "podman-vmalert-logs" "podman-vmalert-metrics" ] (_: {
    requires = [ "init-ghostship-siem-net.service" "siem-egress.service" ];
    after = [ "init-ghostship-siem-net.service" "siem-egress.service"
              "podman-victorialogs.service" "podman-victoriametrics.service" ];
    bindsTo = [ "siem-egress.service" ];
  }) // {
    # A T3 session token for the bridge alone, refreshed daily like the coordinator's.
    ghostship-siem-alerts-t3-token = {
      description = "Issue the SIEM alert bridge's T3 session token";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-t3code.service" ];
      serviceConfig = {
        Type = "oneshot";
        UMask = "0077";
        ExecStart = pkgs.writeShellScript "ghostship-siem-alerts-t3-token" ''
          set -eu
          install -d -m 0700 ${tokenDir}
          for attempt in $(seq 1 30); do
            if token=$(${config.virtualisation.podman.package}/bin/podman exec t3code \
                env HOME=/home/t3code T3CODE_HOME=/home/t3code/.t3 \
                /home/t3code/.local/bin/t3 auth session issue \
                --ttl 30d --label ghostship-siem-alerts --token-only 2>/dev/null) \
                && [ -n "$token" ]; then
              printf '%s' "$token" > ${tokenDir}/t3-token.new
              chmod 0400 ${tokenDir}/t3-token.new
              mv ${tokenDir}/t3-token.new ${tokenDir}/t3-token
              exit 0
            fi
            sleep 10
          done
          echo "could not issue a T3 session token from the t3code container" >&2
          exit 1
        '';
      };
    };
    ghostship-siem-alerts = {
      description = "Deliver SIEM alerts to ntfy and the security campaign thread";
      wantedBy = [ "multi-user.target" ];
      after = [ "podman-vmalert-logs.service" "podman-vmalert-metrics.service"
                "ghostship-siem-alerts-t3-token.service" "ghostship-podman-snapshot.service" ];
      wants = [ "ghostship-siem-alerts-t3-token.service" ];
      serviceConfig = {
        ExecStart = "${bridge}/bin/ghostship-siem-alerts";
        Restart = "always";
        RestartSec = 30;
        StateDirectory = "ghostship-siem-alerts";
        StateDirectoryMode = "0700";
        UMask = "0077";
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        # ghostship-notify keeps its dedupe state here.
        ReadWritePaths = [ "/var/lib/ghostship-notify" "/var/lib/ghostship-container-metrics" ];
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
        CapabilityBoundingSet = "";
        # Root needs no capability to drive the rootful Podman API; hide it.
        InaccessiblePaths = [ "-/run/podman" ];
      };
    };
  };
  systemd.timers.ghostship-siem-alerts-t3-token = {
    wantedBy = [ "timers.target" ];
    timerConfig = { OnBootSec = "10min"; OnCalendar = "daily"; Persistent = true; RandomizedDelaySec = 600; };
  };

  environment.systemPackages = [ bridge ];
}
