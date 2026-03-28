{ config, pkgs, lib, inputs, ... }:

let
  asahiFirmwareDirectory = /boot/asahi;
  hasAsahiFirmwareDirectory = builtins.pathExists asahiFirmwareDirectory;
in
{
  imports = [
    ../../modules/common
    ../../modules/self-hosted
    ./hardware-configuration.nix
  ];

  # Apple Silicon support - handled by nixos-apple-silicon
  hardware.asahi = {
    enable = true;
    setupAsahiSound = false;
    extractPeripheralFirmware = hasAsahiFirmwareDirectory;
  } // lib.optionalAttrs hasAsahiFirmwareDirectory {
    peripheralFirmwareDirectory = asahiFirmwareDirectory;
  };

  # Network
  networking.hostName = "chill-penguin";
  networking.networkmanager.enable = true;

  # Bootloader setup for Asahi
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = false;

  # SSH server
  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "prohibit-password";
    settings.Macs = [
      "hmac-sha2-256"
      "hmac-sha2-512"
      "hmac-sha2-256-etm@openssh.com"
      "hmac-sha2-512-etm@openssh.com"
      "umac-128-etm@openssh.com"
    ];
  };

  # NFS support
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  system.stateVersion = "26.05";
}
