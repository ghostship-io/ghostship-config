{ config, lib, pkgs, ... }:

lib.mkIf (config.wsl.enable or false) {
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  fileSystems."/mnt/z" = {
    device = "192.168.200.106:/volume1/share";
    fsType = "nfs";
    options = [
      "nofail"
      "x-systemd.automount"
      "noatime"
      "nodiratime"
      "soft"
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
