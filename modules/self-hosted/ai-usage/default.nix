# AI usage collection and managed model favorites: one snapshot of every AI account in use,
# written as a node_exporter textfile for VictoriaMetrics and the Grafana
# dashboard provisioned in modules/self-hosted/siem/ui.nix.
#
# The collector is plain Python (standard library only). It never starts,
# stops or restarts a provider, a container or T3 Code. Model preferences use
# authenticated incremental settings patches. Usage is read from what
# already exists - T3 Code's own read-only RPC surface, the provider APIs T3
# Code does not read, the free inference pool, and the public model catalog.
# The contract, every metric name and label, is in README.md.
{ config, lib, pkgs, ... } @ args:
let
  cfg = config.ghostship.aiUsage;
  # The container home the provider credentials, the model catalog and the
  # pool ledger live in. It is not under /home, so ProtectHome is harmless.
  t3Home = "/srv/apps/t3code/home";
  # The textfile directory node_exporter reads (see siem/collection.nix).
  textfileDir = "/var/lib/ghostship-container-metrics";
  output = "${textfileDir}/ai-usage.prom";
  # The ranking keeps its own small state: first seen, evaluations, staleness.
  stateDir = "/var/lib/ghostship-ai-usage";
  state = "${stateDir}/state.json";
  # The Artificial Analysis quality cache, written by the daily pull of the
  # public pages and read by the collector.
  aaCache = "${stateDir}/artificial-analysis.json";
  # The AA-3D board, written by the same pull.
  aa3dCache = "${stateDir}/aa-3d.json";
  # The live model catalog. Only the models it offers have their model page
  # read by the pull.
  modelCatalog = "${t3Home}/.cache/opencode/models.json";
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
  # The owner's runtime policy and picker reconciler. It is a plain source tree from its own
  # flake input. An evaluation that does not carry the flake's inputs (a
  # standalone module test) reads no policy, and the collector reports the
  # policy as unreadable rather than inventing one.
  policy = (args.inputs or { }).ghostship-agent-policy or null;
  policyArg = lib.optionalString (policy != null) (
    " --runtime-policy ${policy}/config/agents/runtime-policy.json"
  );
  # The owner's switch for the routing snapshot. The collector publishes it
  # as it is and never acts on it itself: a consumer reads the switch and
  # decides. Routing stays off until the owner turns it on, so a consumer
  # that ignores the switch still sees it off.
  routingEnabled = if cfg.routing.enabled then "true" else "false";
in
{
  options.ghostship.aiUsage.routing.enabled = lib.mkOption {
    type = lib.types.bool;
    default = false;
    description = ''
      Publish the routing switch of the AI usage snapshot to its consumers.
      The collector writes the switch into the routing snapshot, into every
      projection of it, and into the `ghostship_ai_routing_enabled` gauge.
      Nothing acts on it until the owner turns it on.
    '';
  };

  config = {
    systemd.services.ghostship-ai-usage = {
      description = "Collect AI provider usage, limits, and free models for Prometheus";
      after = [ "network-online.target" "podman.socket" ];
      wants = [ "network-online.target" "podman.socket" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${python}/bin/python3 ${collector}/collector/main.py --output ${output} --state ${state} --snapshot ${routing} --projection ${brokerProjection} --projection ${mcpProjection} --routing-enabled ${routingEnabled}${policyArg}${lib.optionalString (policy != null) " --reconcile-picker"}";
        # The collector finds the T3 Code container's address with the Podman
        # CLI. The CLI must not open the container storage (ProtectSystem makes
        # it read-only), so it asks the Podman API socket instead.
        Environment = [ "CONTAINER_HOST=unix:///run/podman/podman.sock" ]
          ++ lib.optional (policy != null) "PYTHONPATH=${policy}/tools/python";
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
        # The blast radius, stated plainly: the collector runs as root and
        # keeps CAP_DAC_OVERRIDE, because the credentials it must read belong
        # to other users (the mode 0600 files of the container user, the mode
        # 0400 token of the free inference bridge). CAP_DAC_OVERRIDE lets root
        # read any file, and the unit may write the whole of the state
        # directory and the two runtime integration directories, so this is a
        # root equivalent, not a confined reader. Every other capability is
        # dropped, there is no listener, and the collector only ever issues
        # reads and the three atomic writes. Do not read "it only issues GET"
        # as confinement: the honest answer is that the hardening here is the
        # read only code, the fixed paths, and the absence of a listener.
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

    # The Artificial Analysis quality feed is read from the public pages, once
    # a day. There is no key and no account: the pull reads public pages with
    # ordinary GETs, and it keeps the last good snapshot when a page is
    # blocked. The collector only reads the cache the pull wrote.
    systemd.services.ghostship-ai-usage-feed = {
      description = "Pull the Artificial Analysis public pages into the quality cache";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${python}/bin/python3 ${collector}/collector/aa_pull.py --output ${aaCache} --aa3d-output ${aa3dCache} --catalog ${modelCatalog} --model-pages";
        TimeoutStartSec = "10min";
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
        # Only the quality cache is written.
        ReadWritePaths = [
          stateDir
        ];
        MemoryMax = "512M";
        MemoryHigh = "384M";
        CPUQuota = "50%";
        TasksMax = 32;
        CapabilityBoundingSet = [ ];
        AmbientCapabilities = "";
      };
    };

    systemd.timers.ghostship-ai-usage-feed = {
      description = "Pull the Artificial Analysis public pages once a day";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5min";
        OnCalendar = "*-*-* 04:17:00";
        AccuracySec = "5min";
        # A missed pull is not caught up: the next one reads the current pages.
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
  };
}
