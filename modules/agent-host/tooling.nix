{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.agentHost;
in
{
  config = lib.mkIf cfg.enable {
    # Common agent platform utilities installed at system level when agentHost is enabled
    environment.systemPackages = [
      pkgs.git
      pkgs.curl
      pkgs.jq
      pkgs.ripgrep
      pkgs.fd
    ];
  };
}
