{ ... }:

{
  imports = [
    ./wsl.nix
    ./mounts.nix
  ];

  # Windows-side tooling can assume FHS shell paths such as /usr/bin/bash when
  # it connects into the WSL guest.
  services.envfs.enable = true;
}
