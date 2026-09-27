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
    extraFlags = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Additional nixos-rebuild flags for this host's automatic upgrade.";
    };
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
      system.autoUpgrade = {
        enable = true;
        # The repository is public; HTTPS avoids requiring a root GitHub SSH key.
        flake = "git+https://github.com/ghostship-io/ghostship-config.git?ref=main";
        # Deploy the tested committed lock; CI proposes coordinated input updates.
        flags = [ "--no-write-lock-file" ] ++ cfg.extraFlags;
        dates = "04:00";
        randomizedDelaySec = "45min";
        # Catch up after the host was off or rebooted during the window.
        persistent = true;
        allowReboot = false;
      };

      systemd.services.nixos-upgrade = {
        # A switch retried after an interrupted upgrade is idempotent; only
        # avoid starting while a backup holds the maintenance lock.
        preStart = ''
          ${pkgs.util-linux}/bin/flock -w 3600 /run/ghostship-maintenance.lock true
        '';
      };
    })
  ];
}
