{ lib, ... }:

{
  options.ghostship.openchamber = {
    goalMaxAutoTurns = lib.mkOption {
      type = lib.types.ints.positive;
      default = 1000;
      description = "Maximum automatic goal continuations; per-goal token budgets still apply.";
    };
    externalOpenCode.enable = lib.mkEnableOption "canary external OpenCode service for OpenChamber";
    nativeResponses.enable = lib.mkEnableOption "version-gated native OpenAI Responses transport canary";
  };
}
