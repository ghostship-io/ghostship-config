# Public reset discovery has its own cadence; the five-minute collector only reads its cache.
{ pkgs, ... }:
let
  desktop = pkgs.writeShellScript "ai-usage-announcement-desktop" ''
    exec ${pkgs.podman}/bin/podman exec -i ghostship-private-integrations \
      /bin/ghostship-mcp ghostship
  '';
  python = pkgs.python3.withPackages (ps: [ ps.mcp ]);
in
{
  systemd.services.ghostship-ai-usage-announcements = {
    description = "Check public Codex reset announcements through Agent Desktop";
    after = [ "network-online.target" "podman-ghostship-private-integrations.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${python}/bin/python3 ${./collector/announced_resets.py} ${desktop}";
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
