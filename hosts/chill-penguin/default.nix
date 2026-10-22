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
  ghostship.privateIntegrations.enable = true;
  ghostship.privateIntegrations.skillsReconcile.enable = true;
  ghostship.githubEngineering.enable = true;

  ghostship.host.roles = {
    server = true;
  };

  hardware.asahi = {
    enable = true;
    setupAsahiSound = false;
    extractPeripheralFirmware = hasAsahiFirmwareDirectory;
  }
  // lib.optionalAttrs hasAsahiFirmwareDirectory {
    peripheralFirmwareDirectory = asahiFirmwareDirectory;
  };
  hardware.firmwareCompression = "none";

  # CVE-2026-31431: the running Asahi kernel predates the AF_ALG AEAD fix.
  # Deny module autoload and explicit modprobe until a patched kernel is running.
  # This blocks the userspace AEAD interface, not kernel-internal cryptography.
  boot.blacklistedKernelModules = [ "algif_aead" ];
  boot.extraModprobeConfig = ''
    install algif_aead ${pkgs.coreutils}/bin/false
  '';

  # Network
  networking.hostName = "chill-penguin";
  networking.networkmanager.enable = true;
  # The staged development engine may reach public IPv4 only through this NIC.
  ghostship.t3codeDocker.egressInterface = "end0";

  # T3 Code image changes are applied by t3code-deploy-when-idle, never by the switch.
  myOptions.autoUpgrade = {
    enable = true;
    # Pure evaluation cannot see /boot/asahi and would drop peripheral firmware.
    extraFlags = [ "--impure" ];
  };

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
