{ config, pkgs, ... }:
{
  systemd.user.services.opencode-web = {
    description = "OpenCode Web UI (no auto-browser)";
    wantedBy = [ "graphical-session.target" ];
    after = [ "network-online.target" ];
    serviceConfig = {
      ExecStart = "${config.home.homeDirectory}/.local/share/ghostship-agent-tools/npm/bin/opencode web --hostname 0.0.0.0 --port 4096";
      Environment = [ "BROWSER=/bin/false" ];
      Restart = "on-failure";
      RestartSec = "5s";
    };
  };
}