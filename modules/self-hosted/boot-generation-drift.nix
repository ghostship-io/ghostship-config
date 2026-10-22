# An activation must record the system generation: /run/current-system and
# /nix/var/nix/profiles/system must name the same store path. A mismatch that
# lasts longer than ten minutes means a reboot would revert the activation, so
# it reaches operations through ghostship-notify with a stable dedupe key.
{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.bootGenerationDrift;
  settings = pkgs.writeText "ghostship-boot-generation-drift.json" (
    builtins.toJSON {
      state = "/var/lib/ghostship-boot-generation-drift/state.json";
      notify = "${config.ghostship.notify.package}/bin/ghostship-notify";
      current = "/run/current-system";
      profile = "/nix/var/nix/profiles/system";
      # A drift must persist for ten minutes before it is reported.
      threshold = 600;
    }
  );
in
{
  options.ghostship.bootGenerationDrift.enable = lib.mkEnableOption
    "Report a running system that no longer matches the system profile";

  config = lib.mkIf cfg.enable {
    systemd.services.ghostship-boot-generation-drift = {
      description = "Check that the running system matches the system profile";
      serviceConfig = {
        Type = "oneshot";
        StateDirectory = "ghostship-boot-generation-drift";
        StateDirectoryMode = "0700";
        UMask = "0077";
        ExecStart = "${pkgs.python3}/bin/python3 ${./boot-generation-drift.py} --config ${settings}";
        TimeoutStartSec = "1min";
      };
    };
    systemd.timers.ghostship-boot-generation-drift = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2min";
        OnUnitActiveSec = "5min";
        Unit = "ghostship-boot-generation-drift.service";
      };
    };
  };
}
