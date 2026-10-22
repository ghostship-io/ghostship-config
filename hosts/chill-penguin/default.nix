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
  # Model routing is off: the owner turned it off on 2026-10-22. The static
  # worker table (worker_routes in ghostship-agent's runtime policy) governs
  # until the owner approves the selection framework.
  ghostship.aiUsage.routing.enabled = false;
  # Held off by the owner until the coordinator replay fix is deployed and
  # passes a backlog replay.
  ghostship.githubEngineering.coordinatorAutoStart = false;
  ghostship.newsletterHealth.enable = true;
  ghostship.bootGenerationDrift.enable = true;

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

  # Network
  networking.hostName = "chill-penguin";
  networking.networkmanager.enable = true;

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

  # CVE-2026-31431 (algif_aead) and CVE-2026-53266 (ebt_snat), both in CISA KEV:
  # the running 6.19 kernel lacks the fixes. Deny autoload and explicit modprobe
  # until a patched kernel runs. This is containment, not a patched kernel:
  # privileged direct insmod and an already-loaded module stay outside it.
  boot.blacklistedKernelModules = [ "algif_aead" "ebt_snat" ];
  boot.extraModprobeConfig = ''
    install algif_aead ${pkgs.coreutils}/bin/false
    install ebt_snat ${pkgs.coreutils}/bin/false
  '';

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

  # The agent workspace key runs the host command guard as its forced command,
  # so an agent session cannot search the host recursively. The owner's own keys
  # above are authorized without a forced command and are not affected.
  ghostship.sshCommandGuard = {
    enable = true;
    keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAPNLcXkA3IdqGKkbpWyl2xd4v5cCqzp8OblCDILPlL8 agent-workspace@ghostship"
    ];
  };

  # NFS support
  environment.systemPackages = with pkgs; [
    nfs-utils
  ];

  system.stateVersion = "26.05";
}
