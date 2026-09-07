{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.myOptions.autoUpgrade;
in
{
  options.myOptions.autoUpgrade = {
    enable = lib.mkEnableOption "automated system upgrades";
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
      system.autoUpgrade = {
        enable = true;
        flake = "git+ssh://git@github.com/ghostship-io/ghostship-config.git?ref=main";
        # Deploy the tested committed lock; CI proposes coordinated input updates.
        flags = [ "--no-write-lock-file" ];
        dates = "04:00";
        randomizedDelaySec = "45min";
        allowReboot = false;
      };
    })
  ];
}
