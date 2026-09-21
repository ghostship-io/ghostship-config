{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.agentHost;
in
{
  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d /srv/ghostship 0755 root root -"
      "d ${cfg.workspacePath} 0755 ${toString cfg.uid} ${toString cfg.gid} -"
    ];
  };
}
