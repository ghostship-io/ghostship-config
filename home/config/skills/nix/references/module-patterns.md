# NixOS Module Patterns

## Basic Enable/Disable Module
```nix
{ config, lib, pkgs, ... }:
let
  cfg = config.services.my-service;
in {
  options.services.my-service = {
    enable = lib.mkEnableOption "My Service";
    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkgs.my-service ];
    # ...
  };
}
```
