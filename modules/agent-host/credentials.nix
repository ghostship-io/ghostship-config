{ config, lib, ... }:

let
  cfg = config.ghostship.agentHost;
in
{
  config = lib.mkIf cfg.enable {
    # Scoped credential policy: do not inject ambient provider secrets into control plane units.
  };
}
