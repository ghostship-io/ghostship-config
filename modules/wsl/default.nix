{ pkgs, ... }:

let
  envfsWithoutDrvfsPaths = pkgs.envfs.overrideAttrs (oldAttrs: {
    patches = (oldAttrs.patches or [ ]) ++ [
      ./patches/envfs-ignore-drvfs-paths.patch
    ];
  });
in

{
  imports = [
    ./wsl.nix
    ./mounts.nix
  ];

  # Windows PATH import is enabled for desktop interop, but envfs must not
  # synthesize Windows/DrvFS binaries under /usr/bin.
  services.envfs = {
    enable = true;
    package = envfsWithoutDrvfsPaths;
  };
}
