{ ... }:

{
  imports = [
    ./options.nix
    ./lib.nix
    ./packages.nix
    ./base.nix
    ./secrets.nix
    ./retroarch.nix
    ./launchers.nix
    ./tools.nix
    ./frontend.nix
    ./controllers.nix
  ];
}
