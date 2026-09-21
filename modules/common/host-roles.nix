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

    t3worker = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Run this host as an independent T3 Code worker environment.";
    };
  };
}
