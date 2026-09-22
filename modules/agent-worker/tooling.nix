{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.t3Worker;
in
{
  config = lib.mkIf cfg.enable {
    # Direct workers use cloudflared as a persistent outbound connector. Keep
    # it installed with T3 so recovery does not depend on an online download.
    environment.systemPackages = [
      pkgs.cloudflared
      # T3 requires Node 22.16+ / 24; pin the runtime it is tested against.
      pkgs.nodejs_24
    ];
  };
}
