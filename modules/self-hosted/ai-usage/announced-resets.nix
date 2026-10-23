# Public reset discovery has its own cadence; the five-minute collector only reads its cache.
{ pkgs, ... }:
let
  desktop = pkgs.writeShellScript "ai-usage-announcement-desktop" ''
    exec ${pkgs.podman}/bin/podman exec --user 3000:3000 \
      --env HOME=/home/t3code t3code /home/t3code/.local/bin/ghostship-cap "$@"
  '';
in
{
  systemd.services.ghostship-ai-usage-announcements = {
    description = "Check public Codex reset announcements through Agent Desktop";
    after = [ "network-online.target" "podman-t3code.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.python3}/bin/python3 ${./collector/announced_resets.py} ${desktop}";
      TimeoutStartSec = "10min";
      UMask = "0077";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ReadWritePaths = [ "/var/lib/ghostship-ai-usage" ];
      Environment = "CONTAINER_HOST=unix:///run/podman/podman.sock";
      MemoryMax = "128M";
      TasksMax = 32;
    };
  };
  systemd.timers.ghostship-ai-usage-announcements = {
    description = "Check reset announcements at most three times per day";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "7min";
      OnUnitActiveSec = "8h";
      Persistent = false;
    };
  };
}
