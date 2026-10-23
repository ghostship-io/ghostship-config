# Public reset discovery has its own cadence; the five-minute collector only reads its cache.
{ config, pkgs, ... }:
let
  desktop = pkgs.writeShellScript "ai-usage-announcement-desktop" ''
    exec ${pkgs.podman}/bin/podman exec -i ghostship-private-integrations \
      /bin/ghostship-mcp ghostship
  '';
  python = pkgs.python3.withPackages (ps: [ ps.mcp ]);
  confirm = pkgs.writeShellScriptBin "ghostship-ai-confirm-reset" ''
    if [ "$#" -ne 2 ]; then
      echo 'Usage: ghostship-ai-confirm-reset SOURCE_URL RESET_AT_WITH_TIMEZONE' >&2
      exit 2
    fi
    exec ${python}/bin/python3 ${./collector/announced_resets.py} --confirm "$1" --reset-at "$2"
  '';
in
{
  environment.systemPackages = [ confirm ];
  systemd.services.ghostship-ai-usage-announcements = {
    description = "Check public Codex reset announcements through Agent Desktop";
    after = [ "network-online.target" "podman-ghostship-private-integrations.service" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${python}/bin/python3 ${./collector/announced_resets.py} --notify-command ${config.ghostship.notify.package}/bin/ghostship-notify ${desktop}";
      TimeoutStartSec = "10min";
      UMask = "0077";
      NoNewPrivileges = true;
      PrivateTmp = true;
      ProtectSystem = "strict";
      ProtectHome = true;
      ReadWritePaths = [ "/var/lib/ghostship-ai-usage" "/var/lib/ghostship-notify" ];
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
