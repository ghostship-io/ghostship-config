{ pkgs, lib, ... }:

let
  asahiFirmwareDirectory = /boot/asahi;
  hasAsahiFirmwareDirectory = builtins.pathExists asahiFirmwareDirectory;
in
{
  imports = [
    ../../modules/common/default.nix
    ../../modules/self-hosted/default.nix
    ./hardware-configuration.nix
  ];

  # Apple Silicon support - handled by nixos-apple-silicon
  ghostship.host.roles = {
    server = true;
  };

  # Park OpenChamber without removing its declaration or persistent data.
  virtualisation.oci-containers.containers.openchamber.autoStart = false;
  systemd.services.podman-openchamber.enable = false;
  systemd.services.openchamber-deploy-when-idle.enable = false;
  systemd.timers.openchamber-deploy-when-idle.enable = false;

  hardware.asahi = {
    enable = true;
    setupAsahiSound = false;
    extractPeripheralFirmware = hasAsahiFirmwareDirectory;
  }
  // lib.optionalAttrs hasAsahiFirmwareDirectory {
    peripheralFirmwareDirectory = asahiFirmwareDirectory;
  };
  hardware.firmwareCompression = "none";

  # Network
  networking.hostName = "chill-penguin";
  networking.networkmanager.enable = true;

  # Keep the live bus implementation so fleet updates do not require a reboot.
  services.dbus.implementation = "dbus";

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

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMeeTWD0303kIaPcdYjWUGmGYh65TO9wd0kzayjaELhJ owner@dev"
  ];

  # NFS support
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  system.stateVersion = "26.05";
}
