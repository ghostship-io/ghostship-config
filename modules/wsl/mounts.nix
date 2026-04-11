{ config, lib, pkgs, ... }:

lib.mkIf (config.wsl.enable or false) {
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  system.activationScripts.wslResetZMount = {
    text = ''
      # Stop the lazy automount and clear any live NFS mount before systemd
      # reloads the generated /mnt/z units during switch.
      ${pkgs.systemd}/bin/systemctl stop mnt-z.automount mnt-z.mount >/dev/null 2>&1 || true

      if ${pkgs.util-linux}/bin/findmnt -rn -t nfs,nfs4 /mnt/z >/dev/null 2>&1; then
        ${pkgs.util-linux}/bin/umount /mnt/z >/dev/null 2>&1 \
          || ${pkgs.util-linux}/bin/umount -l /mnt/z >/dev/null 2>&1 \
          || true
      fi
    '';
  };

  fileSystems."/mnt/z" = {
    device = "192.168.200.106:/volume1/share";
    fsType = "nfs";
    options = [
      "nofail"
      "x-systemd.automount"
      "noatime"
      "nodiratime"
      "hard"
      "intr"
      "timeo=30"
      "retrans=2"
      "rsize=1048576"
      "wsize=1048576"
      "nfsvers=4.1"
      "async"
      "tcp"
      "actimeo=120"
    ];
  };
}
