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
    githubCredentialFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Root-only Nix access-token configuration for private flake inputs.";
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
        # Flake deployments must not first update obsolete root channels.
        upgrade = false;
        dates = "04:00";
        randomizedDelaySec = "45min";
        # Catch up after the host was off or rebooted during the window.
        persistent = true;
        allowReboot = false;
      };

      systemd.services.nixos-upgrade = {
        serviceConfig.LoadCredential = lib.mkIf (cfg.githubCredentialFile != null) [
          "github-nix.conf:${cfg.githubCredentialFile}"
        ];
        environment.NIX_USER_CONF_FILES = lib.mkIf (cfg.githubCredentialFile != null) "%d/github-nix.conf";
        # Keep the backup lock for the entire build and switch, rather than
        # releasing it in a separate pre-start process.
        script = lib.mkBefore ''
          exec 9>/run/ghostship-maintenance.lock
          ${pkgs.util-linux}/bin/flock -w 3600 9 || exit 1
        '';
      };
    })
  ];
}
