{ config, lib, pkgs, ... }:

let
  # The script that performs the actual mount
  mount-z-script = pkgs.writeShellScriptBin "mount-z" ''
    set -euo pipefail

    # Check if Z: drive is available in Windows
    if /mnt/c/Windows/System32/cmd.exe /c "IF EXIST Z:\ (EXIT 0) ELSE (EXIT 1)" 2>/dev/null; then
        echo "Z: drive detected in Windows."

        # Create mount point if it doesn't exist
        if [ ! -d "/mnt/z" ]; then
            echo "Creating /mnt/z..."
            ${pkgs.coreutils}/bin/mkdir -p /mnt/z
        fi

    # Check if already mounted
        if ${pkgs.util-linux}/bin/mountpoint -q /mnt/z; then
            echo "/mnt/z is already mounted."
        else
            # Get credentials from sops
            SECRETS_FILE=${config.sops.secrets."smb-secrets".path}
            if [ ! -f "$SECRETS_FILE" ]; then
                echo "SMB secrets file not found at $SECRETS_FILE"
                exit 1
            fi
            set -a
            . "$SECRETS_FILE"
            set +a

            echo "Mounting //''${SMB_SERVER}/''${SMB_SHARE} to /mnt/z..."
            if ${pkgs.cifs-utils}/bin/mount.cifs "//''${SMB_SERVER}/''${SMB_SHARE}" /mnt/z \
                -o "username=''${SMB_USER},password=''${SMB_PASS},uid=$(${pkgs.coreutils}/bin/id -u nixos),gid=$(${pkgs.coreutils}/bin/id -g nixos),vers=3.0,iocharset=utf8,rsize=1048576,wsize=1048576,actimeo=60"; then
                echo "Mount successful."
            else
                echo "Mount failed."
                exit 1
            fi
        fi
    else
        echo "Z: drive not found in Windows."
    fi
  '';
in
{
  environment.systemPackages = [ mount-z-script ];

  # Systemd service to run the mount on boot/activation
  systemd.services.mount-z = {
    description = "Mount Windows Z: drive in WSL";
    after = [ "network.target" "sops-nix.service" ];
    wantedBy = [ "multi-user.target" ];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${mount-z-script}/bin/mount-z";
      RemainAfterExit = true;
      User = "root"; # mount needs root
    };
  };
}
