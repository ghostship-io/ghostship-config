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
    options = btrfsSsdOptions;
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
    "d /srv/emulation/cache 0755 kiosk kiosk -"
    "d /srv/emulation/cache/mesa-shaders 0755 kiosk kiosk -"
    "d /srv/emulation/staging 0755 kiosk kiosk -"
    "d /srv/emulation/tmp 1777 root root -"
  ];

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
