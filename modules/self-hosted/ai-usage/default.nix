# AI usage collection: one read-only snapshot of every AI account in use,
# written as a node_exporter textfile for VictoriaMetrics and the Grafana
# dashboard provisioned in modules/self-hosted/siem/ui.nix.
#
# The collector is plain Python (standard library only). It never starts,
# stops or reconfigures a provider, a container or T3 Code: it reads what
# already exists - T3 Code's own read-only RPC surface, the provider APIs T3
# Code does not read, the free inference pool, and the public model catalog.
# The contract, every metric name and label, is in README.md.
{ config, lib, pkgs, ... }:
let
  # The container home the provider credentials, the model catalog and the
  # pool ledger live in. It is not under /home, so ProtectHome is harmless.
  t3Home = "/srv/apps/t3code/home";
  # The textfile directory node_exporter reads (see siem/collection.nix).
  textfileDir = "/var/lib/ghostship-container-metrics";
  output = "${textfileDir}/ai-usage.prom";
  # The ranking keeps its own small state: first seen, evaluations, staleness.
  stateDir = "/var/lib/ghostship-ai-usage";
  state = "${stateDir}/state.json";
  # The routing snapshot is the canonical answer for a consumer. The producer
  # writes it; a consumer only reads it.
  routing = "${stateDir}/routing.json";
  # The same bytes, published to the two runtime directories the broker and
  # the MCP read. They are different directories on the host, and both are
  # bound read only into their container. One producer, no second scorer, no
  # history, and no credential in the file.
  brokerProjection = "/run/ghostship-github/model-routing.json";
  mcpProjection = "/run/ghostship-integrations/model-routing.json";
  # The collector is copied into the store whole, so the unit runs one
  # immutable interpreter over one immutable directory. It talks to T3 Code
  # over a WebSocket with the standard library the platform already uses.
  collector = pkgs.runCommand "ghostship-ai-usage-collector" { } ''
    mkdir -p $out/collector
    cp ${./collector}/*.py $out/collector/
  '';
  python = pkgs.python3.withPackages (ps: [ ps.websockets ]);
in
{
  systemd.services.ghostship-ai-usage = {
    description = "Collect AI provider usage, limits, and free models for Prometheus";
    after = [ "network-online.target" "podman.socket" ];
    wants = [ "network-online.target" "podman.socket" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${python}/bin/python3 ${collector}/collector/main.py --output ${output} --state ${state} --snapshot ${routing} --projection ${brokerProjection} --projection ${mcpProjection}";
      # The collector finds the T3 Code container's address with the Podman
      # CLI. The CLI must not open the container storage (ProtectSystem makes
      # it read-only), so it asks the Podman API socket instead.
      Environment = [ "CONTAINER_HOST=unix:///run/podman/podman.sock" ];
      # The T3 usage summary pages over 30 days and the free pool catalog is
      # paged; a few minutes is the honest bound.
      TimeoutStartSec = "5min";
      # Root, because the provider credentials it reads are root-owned. The
      # unit holds no capabilities, so it opens only what root may open: a
      # credential that only its own uid may read needs a root-owned
      # projection, not a capability.
      UMask = "0077";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectControlGroups = true;
      RestrictNamespaces = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
      MemoryDenyWriteExecute = true;
      SystemCallArchitectures = "native";
      RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
      # Only the textfile and the ranking state are writable.
      ReadWritePaths = [
        textfileDir
        stateDir
        # The two runtime projections, and nothing else in those directories.
        "/run/ghostship-github"
        "/run/ghostship-integrations"
      ];
      # The container home, the published integration files (the T3 endpoint,
      # the session token, the pool socket and token) and the projected
      # provider secrets are read, never written.
      ReadOnlyPaths = [
        t3Home
        "/etc/containers/networks"
        "-/run/ghostship-secrets"
      ];
      # The bounds keep a mistake in the collector from taking the host
      # with it.
      MemoryMax = "512M";
      MemoryHigh = "384M";
      CPUQuota = "50%";
      TasksMax = 32;
      # One capability: the provider credentials belong to the accounts the
      # collector reports on (mode 0600 files of other users, and the
      # directory of the free inference bridge). Every other capability is
      # dropped, the service has no listener, and it writes one textfile and
      # one snapshot. The service runs as root because of this capability, so
      # it is a root equivalent; it is kept to one read only collector with
      # no listener and no write outside its two directories.
      CapabilityBoundingSet = [ "CAP_DAC_OVERRIDE" ];
      AmbientCapabilities = "";
    };
  };

  systemd.timers.ghostship-ai-usage = {
    description = "Refresh the AI usage metrics every five minutes";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2min";
      OnUnitActiveSec = "5min";
      AccuracySec = "1s";
      # A missed run is not caught up: the next one reads the current state.
      Persistent = false;
    };
  };

  systemd.tmpfiles.rules = [
    "d ${textfileDir} 0755 root root -"
    # The directory holds the ranking state and the routing snapshot. The
    # snapshot is read by the consumer, so the directory is readable but
    # only the producer writes it.
    "d ${stateDir} 0755 root root -"
  ];
}
