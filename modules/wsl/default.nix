{ pkgs, ... }:

{
  imports = [
    ./wsl.nix
    ./mounts.nix
  ];

  # Windows-side tooling can assume FHS executable paths such as /usr/bin/bash
  # and /usr/bin/gh when it connects into the WSL guest.
  services.envfs = {
    enable = true;
    extraFallbackPathCommands = ''
      ln -s ${pkgs.gh}/bin/gh $out/gh
    '';
  };
}
