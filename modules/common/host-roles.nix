{ lib, ... }:

{
  options.ghostship.host.roles = {
    server = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the minimal server profile.";
    };

    develop = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the richer development profile.";
    };

    wsl = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable WSL-specific integration.";
    };
  };
}
