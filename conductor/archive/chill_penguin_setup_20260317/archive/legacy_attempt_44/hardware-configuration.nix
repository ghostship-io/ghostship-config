{ config, lib, pkgs, modulesPath, ... }:

{
  imports = [
    (modulesPath + "/installer/scan/not-detected.nix")
  ];

  # ULTIMATE MINIMAL initrd for bootstrap
  boot.initrd.includeDefaultModules = false;
  boot.initrd.systemd.enable = true;
  
  boot.initrd.availableKernelModules = lib.mkForce [
    "nvme_apple"
    "apple_sart"
    "apple-mailbox"
    "apple-dart"
    "pcie-apple"
    "usb-storage"
    "appledrm"
    "macsmc"
    "macsmc-power"
    "macsmc-reboot"
    "rtc-macsmc"
    "apple-rtkit-helper"
    "pinctrl-apple-gpio"
    "i2c-pasemi-platform"
    "i2c_pasemi_core"
    "spi-apple"
    "spmi-apple-controller"
    "nvmem_spmi_mfd"
    "nvmem-apple-efuses"
  ];

  boot.initrd.kernelModules = [ ];
  boot.kernelModules = [ ];
  boot.extraModulePackages = [ ];

  # File Systems based on Fedora Audit
  fileSystems."/" =
    { device = "/dev/disk/by-uuid/72bd8b6f-0e7f-46f2-a181-6560211eabe7";
      fsType = lib.mkForce "btrfs";
      options = [ "subvol=nixos-root" "compress=zstd" "noatime" ];
    };

  fileSystems."/boot" =
    { device = "/dev/disk/by-uuid/2cd4968a-3953-4afe-9818-d9c10317e4a5";
      fsType = "ext4";
    };

  fileSystems."/boot/efi" =
    { device = "/dev/disk/by-uuid/5CDF-1DF4";
      fsType = "vfat";
    };

  fileSystems."/home" =
    { device = "/dev/disk/by-uuid/72bd8b6f-0e7f-46f2-a181-6560211eabe7";
      fsType = "btrfs";
      options = [ "subvol=nixos-home" "compress=zstd" "noatime" ];
    };

  swapDevices = [ ];

  networking.useDHCP = lib.mkDefault true;

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";
}
