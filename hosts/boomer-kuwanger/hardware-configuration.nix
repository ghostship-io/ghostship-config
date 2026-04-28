{ config, lib, pkgs, modulesPath, ... }:

let
  btrfsSsdOptions = [ "noatime" "compress=zstd:1" "discard=async" ];
in

{
  imports = [
    (modulesPath + "/installer/scan/not-detected.nix")
  ];

  boot.initrd.availableKernelModules = [ "nvme" "xhci_pci" "ahci" "usbhid" "usb_storage" "sd_mod" ];
  boot.initrd.kernelModules = [ "amdgpu" ];
  boot.kernelModules = [ "kvm-amd" ];
  boot.extraModulePackages = [ ];

  # Bootloader
  boot.loader.systemd-boot.enable = lib.mkDefault true;
  boot.loader.efi.canTouchEfiVariables = lib.mkDefault true;

  fileSystems."/boot" = {
    device = "/dev/disk/by-label/BOOT";
    fsType = "vfat";
    options = [ "umask=0077" ];
  };

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [ "subvol=@" ] ++ btrfsSsdOptions;
  };

  fileSystems."/nix" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [ "subvol=@nix" ] ++ btrfsSsdOptions;
  };

  fileSystems."/home" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [ "subvol=@home" ] ++ btrfsSsdOptions;
  };

  fileSystems."/fast" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [ "subvol=@fast" ] ++ btrfsSsdOptions;
  };

  fileSystems."/srv/emulation/roms" = {
    device = "/dev/disk/by-label/roms";
    fsType = "btrfs";
    options = btrfsSsdOptions ++ [ "nofail" "x-systemd.device-timeout=10s" ];
  };

  swapDevices = [
    { device = "/dev/disk/by-label/swap"; }
  ];

  systemd.tmpfiles.rules = [
    "d /fast 0755 root root -"
    "d /fast/emulation 0755 kiosk kiosk -"
    "d /fast/emulation/cache 0755 kiosk kiosk -"
    "d /fast/emulation/cache/mesa-shaders 0755 kiosk kiosk -"
    "d /fast/emulation/staging 0755 kiosk kiosk -"
    "d /fast/emulation/tmp 1777 root root -"
    "d /fast/nix-build 1777 root root -"
  ];

  nix.settings.build-dir = "/fast/nix-build";

  # Minisforum HX100G specific hardware tweaks:
  # Ryzen 7840HS + Radeon RX 6650M.

  # Enable amdgpu for both integrated and discrete graphics
  services.xserver.videoDrivers = [ "amdgpu" ];

  # AMD P-State EPP for Zen 4 (7840HS)
  boot.kernelParams = [ "amd_pstate=active" ];

  networking.useDHCP = lib.mkDefault true;

  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
  hardware.cpu.amd.updateMicrocode = lib.mkDefault config.hardware.enableRedistributableFirmware;
}
