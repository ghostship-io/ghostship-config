# A running host that is no longer the configuration main names is a
# change-control problem, not a reason to switch unattended. This service
# compares the running system with the system profile and the running
# configuration revision with main once a day, and reports a security alert
# through ghostship-notify. It never builds, switches, sets the profile,
# activates a generation, stops a timer or restarts a service: the host links
# are read-only, and the only writes are the private state directory and the
# notification delivery.
#
# The running revision is the one the running system recorded in
# `nixos-version --configuration-revision`, written from
# `system.configurationRevision = self.rev` at build time. It is never read
# from the source checkout or the evaluated candidate, so a checkout that
# happens to be newer cannot make a stale host look current. A missing or
# dirty revision is an error, never health.
{ config, lib, pkgs, self, ... }:

let
  cfg = config.ghostship.configurationDrift;
  stateDir = "/var/lib/ghostship-configuration-drift";
  revision = self.rev or null;
  settings = pkgs.writeText "ghostship-configuration-drift.json" (
    builtins.toJSON {
      state = stateDir;
      notify = "${config.ghostship.notify.package}/bin/ghostship-notify";
      git = "${pkgs.git}/bin/git";
      # The same public source as modules/common/automation.nix; HTTPS needs
      # no host credential.
      remote = "https://github.com/ghostship-io/ghostship-config.git";
      branch = "main";
      running_system = "/run/current-system";
      profile = "/nix/var/nix/profiles/system";
      # A drift must last longer than one day before it is reported.
      threshold = 86400;
    }
  );
in
{
  options.ghostship.configurationDrift.enable = lib.mkEnableOption
    "Report a running configuration that no longer matches the source main";

  config = lib.mkIf cfg.enable {
    # Record the flake revision in the running system. nixos-version exposes
    # it as --configuration-revision, which is the only revision the check
    # trusts for the running side.
    system.configurationRevision = lib.mkDefault (
      if revision == null then "dirty" else revision
    );

    systemd.services.ghostship-configuration-drift = {
      description = "Report a running configuration that drifts from main";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.python3}/bin/python3 ${./configuration-drift.py} --config ${settings}";
        StateDirectory = "ghostship-configuration-drift";
        StateDirectoryMode = "0700";
        UMask = "0077";
        TimeoutStartSec = "5min";
        # The host links, the running generation and the system profile are
        # read-only. StateDirectory is the only writable host path, and the
        # notifier's dedupe state stays inside it too.
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        NoNewPrivileges = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictNamespaces = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        SystemCallArchitectures = "native";
        RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
        CapabilityBoundingSet = "";
        ReadOnlyPaths = [
          "/run/current-system"
          "/nix/var/nix/profiles/system"
        ];
        Environment = [ "GHOSTSHIP_NOTIFY_STATE=${stateDir}/notify" ];
      };
    };
    systemd.timers.ghostship-configuration-drift = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "15min";
        OnCalendar = "daily";
        Persistent = true;
        RandomizedDelaySec = "30min";
        Unit = "ghostship-configuration-drift.service";
      };
    };
  };
}
