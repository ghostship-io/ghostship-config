{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.ghostship.security;
  stateDir = "/var/lib/ghostship-security";
  flowRules = pkgs.writeText "security-flows.nft" (builtins.readFile ./security-flows.nft);
  profiled = lib.filter (app: app.apparmorProfile != null) (lib.attrValues config.ghostship.apps);
  checkConfig = pkgs.writeText "ghostship-security-check.json" (
    builtins.toJSON {
      ntfy_topic = cfg.ntfyTopic;
      expected_profiles = lib.attrNames (
        lib.filterAttrs (_: policy: policy.state != "disable") config.security.apparmor.policies
      );
      container_profiles = builtins.listToAttrs (
        map (app: lib.nameValuePair app.container app.apparmorProfile) profiled
      );
      expected_tables = [
        "inet ghostship_flows"
        "bridge ghostship_flows"
        "inet ghostship_flaresolverr"
        "bridge ghostship_flaresolverr"
      ];
      declared_containers = lib.attrNames config.virtualisation.oci-containers.containers;
      ephemeral_prefixes = [
        "gluetun-bench-"
        "pyload-restart-failed"
      ];
      inherit (cfg)
        privileged_allow
        cap_add_allow
        socket_mount_allow
        ssh_allowed_sources
        host_ssh_clients
        database_owners
        ;
      ssh_failure_threshold = 10;
      flows_state = "${stateDir}/flows.json";
    }
  );
  tools = [
    pkgs.nftables
    config.virtualisation.podman.package
    pkgs.iproute2
    pkgs.audit
    pkgs.systemd
    pkgs.coreutils
    pkgs.findutils
  ];
  flows = pkgs.writeShellApplication {
    name = "ghostship-flow-report";
    runtimeInputs = tools;
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./security-flows.py} \
        --name ${cfg.synologyAddress}=synology "$@"
    '';
  };
  check = pkgs.writeShellApplication {
    name = "ghostship-security-check";
    runtimeInputs = tools ++ [ config.ghostship.notify.package ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./security-check.py} --config ${checkConfig} "$@"
    '';
  };
  oneshot = description: exec: {
    inherit description;
    onFailure = [ "ghostship-failure@%n.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = exec;
      StateDirectory = "ghostship-security";
      StateDirectoryMode = "0700";
      UMask = "0077";
      TimeoutStartSec = "30min";
      Nice = 10;
      IOSchedulingClass = "idle";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "full";
    };
  };
in
{
  options.ghostship.security = {
    ntfyTopic = lib.mkOption {
      type = lib.types.str;
      default = "security";
      description = "NTFY topic for host security findings, published through ghostship-notify.";
    };
    synologyAddress = lib.mkOption {
      type = lib.types.str;
      default = "192.168.4.241";
    };
    privileged_allow = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "t3code" ];
      description = "Containers allowed to run privileged. T3 is the tracked exception until its Docker split (issue 102).";
    };
    cap_add_allow = lib.mkOption {
      type = lib.types.attrsOf (lib.types.listOf lib.types.str);
      default.gluetun = [ "CAP_NET_ADMIN" ];
    };
    socket_mount_allow = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
    };
    ssh_allowed_sources = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "10.89.7.3/32"
        "10.89.0.15/32"
        "10.89.0.150/32"
      ];
      description = "Root SSH login sources: T3 on both networks and the Access-gated tunnel connector.";
    };
    host_ssh_clients = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "t3code"
        "cloudflared"
      ];
    };
    database_owners = lib.mkOption {
      type = lib.types.attrsOf (lib.types.listOf lib.types.str);
      default = {
        romm-db = [
          "romm"
          "uptime-kuma"
        ];
        grimmory-db = [
          "grimmory"
          "uptime-kuma"
        ];
      };
    };
  };

  config = {
    environment.systemPackages = [
      flows
      check
    ];

    # Observe-only: the tables hold no verdicts, so loading or dropping them
    # never changes which packets pass.
    systemd.services.ghostship-flow-observer = {
      description = "Record new container and host connections for the allow graph";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-pre.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.nftables}/bin/nft -f ${flowRules}";
        ExecStop = [
          "${pkgs.nftables}/bin/nft destroy table inet ghostship_flows"
          "${pkgs.nftables}/bin/nft destroy table bridge ghostship_flows"
        ];
      };
    };

    systemd.services.ghostship-flow-collect =
      lib.recursiveUpdate (oneshot "Aggregate observed flows into the container edge map" "${lib.getExe flows} collect")
        {
          after = [ "ghostship-flow-observer.service" ];
          requires = [ "ghostship-flow-observer.service" ];
        };
    systemd.timers.ghostship-flow-collect = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5min";
        OnUnitActiveSec = "5min";
      };
    };

    systemd.services.ghostship-security-check =
      lib.recursiveUpdate (oneshot "Check host security invariants and drift" (lib.getExe check))
        {
          after = [
            "ghostship-flow-collect.service"
            "apparmor.service"
          ];
        };
    systemd.timers.ghostship-security-check = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "10min";
        OnUnitActiveSec = "15min";
        RandomizedDelaySec = "60";
      };
    };
  };
}
