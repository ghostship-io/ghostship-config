# Read-only, bounded snapshots into the existing SIEM stores. No listener,
# credentials, orchestration permissions, extra database or external network.
{ config, lib, pkgs, ... }:
let
  textfile = "/var/lib/ghostship-container-metrics";
  output = "/run/ghostship-autonomous-work";
  t3Home = "/srv/apps/t3code/home";
  collectorConfig = pkgs.writeText "autonomous-work.json" (builtins.toJSON {
    host = config.networking.hostName;
    # The stock runtime's state directory holds the environment id; the
    # collector reads that existing file read-only (UUID only), so the id is
    # never baked into configuration or the store.
    environment_id_file = "${t3Home}/.t3/userdata/environment-id";
    t3_db = "${t3Home}/.t3/userdata/statev2.sqlite";
    coordinator_db = "/var/lib/ghostship-github/state/github.sqlite";
    runtime_db = "${t3Home}/.local/state/ghostship-agent/runtime/jobs.sqlite";
    mcp_runtime_db = "/srv/apps/ghostship-private-integrations/ghostship/ghostship-agent/runtime/jobs.sqlite";
    mcp_runtime_alternates = [
      "/srv/apps/ghostship-private-integrations/backend/.local/state/ghostship-agent/runtime/jobs.sqlite"
      "/srv/apps/ghostship-private-integrations/ghostship/.local/state/ghostship-agent/runtime/jobs.sqlite"
    ];
    metrics = "${textfile}/autonomous-work.prom";
    snapshot = "${output}/snapshot.jsonl";
  });
in
{
  systemd.services.ghostship-autonomous-work = {
    description = "Read-only autonomous work observations for Grafana";
    after = [ "local-fs.target" ];
    path = [ pkgs.systemd ];
    serviceConfig = {
      Type = "oneshot";
      # Vector already belongs to this logging-reader group. Operational rows
      # include private branches and model selections; only metrics are public.
      Group = "systemd-journal";
      ExecStart = "${pkgs.python3}/bin/python3 ${./autonomous-work.py} ${collectorConfig}";
      # Root may traverse the existing private stores, but cannot modify them.
      # mode=ro + query_only + read-only mounts preserve live WAL semantics.
      ProtectSystem = "strict";
      ReadOnlyPaths = [
        "-${t3Home}/.t3/userdata"
        "-${t3Home}/.local/state/ghostship-agent/runtime"
        "-/var/lib/ghostship-github/state"
        "-/srv/apps/ghostship-private-integrations/ghostship/ghostship-agent/runtime"
        "-/srv/apps/ghostship-private-integrations/backend/.local/state/ghostship-agent/runtime"
        "-/srv/apps/ghostship-private-integrations/ghostship/.local/state/ghostship-agent/runtime"
      ];
      ReadWritePaths = [ output textfile ];
      RuntimeDirectory = "ghostship-autonomous-work";
      RuntimeDirectoryMode = "0750";
      RuntimeDirectoryPreserve = true;
      ProtectHome = true;
      PrivateTmp = true;
      PrivateNetwork = true;
      RestrictAddressFamilies = [ "AF_UNIX" ];
      CapabilityBoundingSet = [ "CAP_DAC_READ_SEARCH" ];
      NoNewPrivileges = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectControlGroups = true;
      RestrictNamespaces = true;
      LockPersonality = true;
      MemoryDenyWriteExecute = true;
      MemoryMax = "128M";
      CPUQuota = "10%";
      Nice = 15;
      TimeoutStartSec = "30s";
      UMask = "0022";
    };
  };
  systemd.timers.ghostship-autonomous-work = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2min";
      OnUnitActiveSec = "60s";
      AccuracySec = "5s";
    };
  };
  systemd.tmpfiles.rules = [ "d ${textfile} 0755 root root -" ];

  # exec reads one atomic bounded snapshot per poll. Vector timestamps and
  # disk buffering remain the existing delivery/retention mechanisms.
  services.vector.settings.sources.autonomous_work = {
    type = "exec";
    mode = "scheduled";
    scheduled.exec_interval_secs = 60;
    command = [ "${pkgs.coreutils}/bin/cat" "${output}/snapshot.jsonl" ];
    decoding.codec = "json";
  };
  services.vector.settings.transforms.autonomous_work_shape = {
    type = "remap";
    inputs = [ "autonomous_work" ];
    # exec adds command/pid/stream metadata. Drop everything except the
    # collector contract, and preserve collection time across repeated reads.
    source = let
      fields = [
        "host" "source" "kind" "work_id" "status" "event_at" "next_at"
        "trigger" "thread_url" "github_url" "provider"
        "unit" "coverage" "reason" "rows" "limited"
        "duration_seconds" "fired_at" "event" "event_seconds"
        "fired_seconds" "project_id" "thread_count" "occupied"
        "route_state" "primary_quota" "route_reason" "fallback"
        "switch_accepted" "message_accepted" "native_run_count" "executing_count"
        "enabled" "last_status" "evidence" "event_today" "fired_today" "action"
        "outcome" "merged" "required_checks" "failed_checks" "revision" "owner_state"
        "model" "branch" "parent_url" "total"
      ];
    in ''
      original = .
      . = {
        ${lib.concatMapStringsSep ",\n" (field: "\"${field}\": original.${field}") fields}
      }
      .stream = "autonomous-work"
      .message = "Autonomous work observation"
      .timestamp = parse_timestamp!(string!(original.snapshot_at), format: "%+")
    '';
  };
  services.vector.settings.transforms.redacted.inputs = [ "autonomous_work_shape" ];
}
