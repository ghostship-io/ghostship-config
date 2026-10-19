{
  config,
  lib,
  pkgs,
  ...
}:
let
  credentials = config.ghostship.selfHostedSecrets.projections.synology-snmp.path;
  # SNMPv3 authPriv (SHA, AES) poll of the NAS; findings go to the operations
  # topic. DSM's own notifications arrive separately through its webhooks.
  check = pkgs.writeShellApplication {
    name = "ghostship-synology-health";
    runtimeInputs = [
      pkgs.net-snmp
      config.ghostship.notify.package
    ];
    text = ''
      exec ${pkgs.python3}/bin/python3 ${./synology-health.py} \
        --host ${config.ghostship.security.synologyAddress} --credentials ${credentials} "$@"
    '';
  };
in
{
  environment.systemPackages = [ check ];

  systemd.services.ghostship-synology-health = {
    description = "Poll Synology disk, RAID, volume, temperature and system health over SNMPv3";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = lib.getExe check;
      StateDirectory = "ghostship-synology-health";
      StateDirectoryMode = "0700";
      UMask = "0077";
      TimeoutStartSec = "10min";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "full";
    };
  };
  systemd.timers.ghostship-synology-health = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "10min";
      OnUnitActiveSec = "10min";
      RandomizedDelaySec = "60";
    };
  };
}
