{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };
in
{
  systemd.services.ghostship-agent-maintenance = {
    description = "Refresh installed agent CLIs and shared agent assets";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      User = "nixos";
      Group = "nixos";
      WorkingDirectory = "/home/nixos";
      Environment = [
        "HOME=/home/nixos"
      ];
      ExecStart = "${agentTooling.agentMaintenance}/bin/ghostship-agent-maintenance";
    };
  };

  systemd.timers.ghostship-agent-maintenance = {
    description = "Refresh installed agent CLIs and shared agent assets every 4 hours";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "2m";
      OnUnitActiveSec = "4h";
      Persistent = true;
      Unit = "ghostship-agent-maintenance.service";
    };
  };
}
