{ config, pkgs, inputs, lib, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/common/default.nix
    # ../../modules/common/secrets.nix  # Temporarily disabled for cross-build
    ../../modules/common/user-nixos.nix
    # Apple Silicon support is provided via the nixos-apple-silicon module in flake.nix
  ];

  # Temporary password until sops is restored on the host
  users.users.nixos = {
    initialPassword = "nixos";
    hashedPasswordFile = lib.mkForce null;
  };
  users.mutableUsers = lib.mkForce true;

  # Apple Silicon Specifics
  hardware.asahi = {
    enable = true;
    # Use LTS kernel for better compatibility/stability during bootstrap
    # (nixos-apple-silicon module handles the package selection usually, but we can force it)
    # Actually, let's keep the module default but ensure we are using the stable channel
    
    # Headless setup for Mac Studio
    setupAsahiSound = false; # Headless
    # Firmware extraction from the active EFI partition
    peripheralFirmwareDirectory = "/boot/efi/asahi";
    extractPeripheralFirmware = false; # Set to false for remote evaluation/build
  };

  # Binary Cache for Apple Silicon
  nix.settings = {
    substituters = [ "https://nixos-apple-silicon.cachix.org" ];
    trusted-public-keys = [ "nixos-apple-silicon.cachix.org-1:99u9ab+GY9ST64WcjF0QMnqKSCDasA/6bGuD6uQB9vY=" ];
  };

  # Bootloader
  # Use GRUB as recommended for Apple Silicon (systemd-boot is less mature here)
  boot.loader.grub = {
    enable = true;
    efiSupport = true;
    efiInstallAsRemovable = true;
    device = "nodev";
    useOSProber = true;
    extraEntries = ''
      menuentry "Fedora Asahi Linux" {
        search --fs-uuid --set=root 2cd4968a-3953-4afe-9818-d9c10317e4a5
        configfile ($root)/grub2/grub.cfg
      }
    '';
  };
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  boot.loader.efi.canTouchEfiVariables = false;

  # Kernel Parameters from Audit (NixOS Adapted)
  boot.kernelParams = [
    "ro"
    "rootflags=subvol=nixos-root"
    "console=ttyAIC0"
    "console=tty0"
    "apple_dcp.adp_enabled=1"
    "efi=no_attributes"
    "pci=pcie_aspm=off"
    "module_blacklist=sdhci_pci"
  ];

  # Networking
  networking.hostName = "chill-penguin";
  networking.networkmanager.enable = true;

  # Headless Optimizations
  services.openssh = {
    enable = true;
    settings = {
      PermitRootLogin = "no";
      PasswordAuthentication = false;
    };
  };

  # State version
  system.stateVersion = "25.11";

  # Use our custom EFI-wrapped Asahi kernel
  boot.kernelPackages = lib.mkForce (pkgs.linuxPackagesFor pkgs.linux-asahi-custom);

  # Override common packages to keep initial install minimal
  environment.systemPackages = with pkgs; [
    coreutils
    bash
    git
    neovim
    curl
    wget
    htop
    jq
    zoxide
    fd
    fzf
    btop
    zstd
    pciutils
    usbutils
    grub2_efi
    efibootmgr
    # Keep it bare minimum for the first boot over SSH
  ];
}
