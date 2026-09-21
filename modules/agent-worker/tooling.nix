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
    # T3 Connect resolves the cloudflared relay client on the caller's PATH.
    # The package keeps the first Connect attempt offline-tolerant instead of
    # relying on T3 Code's download during setup.
    environment.systemPackages = [
      pkgs.cloudflared
      # T3 requires Node 22.16+ / 24; pin the runtime it is tested against.
      pkgs.nodejs_24
    ];
  };
}
