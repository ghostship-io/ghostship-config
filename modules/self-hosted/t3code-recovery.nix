{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  source = lib.cleanSourceWith {
    src = ../../packages/t3code/recovery;
    filter =
      path: type:
      if type == "directory" then
        builtins.baseNameOf path != "__pycache__"
      else
        lib.hasSuffix ".py" path || lib.hasSuffix ".json" path;
  };
  codex = pkgs.callPackage ../../packages/t3code/recovery/codex.nix { };
  python = pkgs.python3;
  probe = pkgs.callPackage "${inputs.ghostship-private-agent}/packages/t3code/activity-probe/default.nix" { };
  runtime = "/run/t3code-recovery";
  home = "/srv/apps/t3code/home";
  advisorHome = "/run/t3code-advisor/home";
  auth = "${home}/.codex/auth.json";
  identity = "${runtime}/auth-identity.json";
  schema = "${source}/schema.json";
  # Owner automation request, 2026-10-23: independently recover eligible sustained
  # T3 outages under the deterministic controller's bounded remedy policy.
  approval = "owner-automation-request-2026-10-23";
  recoveryConfig = pkgs.writeText "t3code-recovery.json" (
    builtins.toJSON {
      state_dir = "/var/lib/t3code-recovery";
      runtime_dir = runtime;
      home_dir = home;
      deployment_state_dir = "/var/lib/ghostship/t3code-deployment";
      podman_bin = "${pkgs.podman}/bin/podman";
      systemctl_bin = "${pkgs.systemd}/bin/systemctl";
      nsenter_bin = "${pkgs.util-linux}/bin/nsenter";
      curl_bin = "${pkgs.curl}/bin/curl";
      probe_bin = "${probe}/bin/t3code-activity-probe";
      advisor_unit = "t3code-recovery-advisor.service";
      owner_approval = approval;
    }
  );
  controller = pkgs.writeShellScriptBin "t3code-recovery" ''
    exec ${pkgs.python3}/bin/python3 ${source}/controller.py --config ${recoveryConfig} "$@"
  '';
  advisor = pkgs.writeShellScriptBin "t3code-recovery-advisor" ''
    exec ${python}/bin/python3 ${source}/advisor.py \
      --codex ${codex}/bin/codex --schema ${schema} \
      --identity ${identity} --diagnostics ${runtime}/advisor/diagnostics.json \
      --output ${runtime}/advisor/proposal.json --home ${advisorHome} \
      --ca ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
  '';
  bounds = {
    MemoryMax = "1G";
    TasksMax = 256;
    CPUQuota = "100%";
    KillMode = "control-group";
    TimeoutStopSec = 10;
    UMask = "0077";
  };
in
{
  system.build.t3codeRecoveryController = controller;
  system.build.t3codeRecoveryAdvisor = advisor;
  system.build.t3codeRecoveryConfig = recoveryConfig;
  system.build.t3codeRecoveryCodex = codex;
  system.build.t3codeRecoveryUnits = pkgs.linkFarm "t3code-recovery-units" (
    map
      (name: {
        inherit name;
        path = "${config.systemd.units.${name}.unit}/${name}";
      })
      [
        "t3code-recovery.service"
        "t3code-recovery-advisor.service"
        "t3code-recovery-advisor-auth.service"
      ]
  );
  assertions = [
    {
      assertion = codex.version == "0.163.0";
      message = "Recovery advisor must be revalidated before changing its pinned Codex version.";
    }
  ];

  systemd.tmpfiles.rules = [
    "d ${runtime} 0755 root root -"
    "d ${runtime}/advisor 0700 3000 3000 -"
    "d /var/lib/t3code-recovery 0700 root root -"
  ];
  systemd.services.t3code-recovery = {
    description = "Independent bounded T3 recovery controller";
    wantedBy = [ "multi-user.target" ];
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    # No dependency on Podman or T3: an application outage must not stop recovery.
    serviceConfig = bounds // {
      Type = "exec";
      User = "root";
      ExecStart = lib.getExe controller;
      Restart = "always";
      RestartSec = 30;
      # This controller is a persistent observer, not one bounded repair task.
      # A finite unit lifetime kills healthy observation every 20 minutes and
      # creates an avoidable recovery gap. Commands and the advisor retain
      # their own deadlines; resource and stop bounds still apply here.
      RuntimeMaxSec = "infinity";
    };
  };
  systemd.services.t3code-recovery-advisor-auth = {
    description = "Check live advisor credential source without exposing its values";
    serviceConfig = bounds // {
      Type = "oneshot";
      User = "root";
      TimeoutStartSec = 15;
      ExecStart = "${python}/bin/python3 ${source}/advisor.py --preflight-auth ${auth} --identity ${identity}";
    };
  };
  systemd.services.t3code-recovery-advisor = {
    description = "Tool-free bounded T3 recovery advisor";
    # The separate root preflight sees the host source before namespace masking.
    requires = [ "t3code-recovery-advisor-auth.service" ];
    after = [ "t3code-recovery-advisor-auth.service" ];
    # Started only by the controller, never at boot or via a timer.
    serviceConfig = bounds // {
      Type = "exec";
      User = "3000";
      Group = "3000";
      RuntimeMaxSec = 480;
      Restart = "no";
      ExecStart = lib.getExe advisor;
      CapabilityBoundingSet = "";
      NoNewPrivileges = true;
      ProtectSystem = "strict";
      ProtectHome = "tmpfs";
      PrivateTmp = true;
      PrivateDevices = true;
      ProtectProc = "invisible";
      ProcSubset = "pid";
      ProtectKernelTunables = true;
      ProtectKernelModules = true;
      ProtectKernelLogs = true;
      ProtectControlGroups = true;
      RestrictSUIDSGID = true;
      LockPersonality = true;
      RestrictNamespaces = true;
      RestrictRealtime = true;
      RestrictAddressFamilies = [
        "AF_INET"
        "AF_INET6"
      ];
      TemporaryFileSystem = [
        "/srv:ro"
        "/var:ro"
        "/workspace:ro"
        "/run:ro"
        "/run/t3code-advisor:rw,size=64M,mode=0700,uid=3000,gid=3000"
        "${advisorHome}:rw,size=64M,mode=0700,uid=3000,gid=3000"
      ];
      BindReadOnlyPaths = [
        "${auth}:${advisorHome}/auth.json"
        "${runtime}/advisor/diagnostics.json"
        identity
        schema
      ];
      # Only this single exchange output can be changed outside private tmpfs.
      BindPaths = [ "${runtime}/advisor/proposal.json" ];
      ReadWritePaths = [ "${runtime}/advisor/proposal.json" ];
      InaccessiblePaths = [ "/root" ];
      Environment = [ "CODEX_REFRESH_TOKEN_URL_OVERRIDE=http://127.0.0.1:9" ];
    };
  };
}
