{ lib, ... }:

{
  options.ghostship.openchamber = {
    externalOpenCode.enable = lib.mkEnableOption "canary external OpenCode service for OpenChamber";
    nativeResponses.enable = lib.mkEnableOption "version-gated native OpenAI Responses transport canary";
  };
}
