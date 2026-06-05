{
  config,
  lib,
  pkgs,
  ...
}:

lib.mkIf (config.wsl.enable or false) {
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  system.activationScripts.wslResetZMount = {
    text = ''
      # Stop the lazy automount and clear any live NFS mount before systemd
      # reloads the generated /mnt/share units during switch. Also clear the
      # retired /mnt/z units so the path migration does not leave stale mounts.
      ${pkgs.systemd}/bin/systemctl stop mnt-share.automount mnt-share.mount >/dev/null 2>&1 || true
      ${pkgs.systemd}/bin/systemctl stop mnt-z.automount mnt-z.mount >/dev/null 2>&1 || true

      for mountpoint in /mnt/share /mnt/z; do
        if ${pkgs.util-linux}/bin/findmnt -rn -t nfs,nfs4 "$mountpoint" >/dev/null 2>&1; then
          ${pkgs.util-linux}/bin/umount "$mountpoint" >/dev/null 2>&1 \
            || ${pkgs.util-linux}/bin/umount -l "$mountpoint" >/dev/null 2>&1 \
            || true
        fi
      done
    '';
  };

  fileSystems."/mnt/share" = {
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
