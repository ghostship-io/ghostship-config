{ lib, osConfig, ... }:

let
  roles = osConfig.ghostship.host.roles or { };
in
{
  imports = [ ./profiles/base.nix ]
    ++ lib.optional (roles.server or false) ./profiles/server.nix
    ++ lib.optional (roles.develop or false) ./profiles/develop.nix
    ++ lib.optional (roles.wsl or false) ./profiles/wsl.nix;

  home.stateVersion = "25.11";
}
