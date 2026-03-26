{ config, pkgs, lib, modulesPath, ... }:

{
  imports = [
    (modulesPath + "/profiles/base.nix")
    (modulesPath + "/profiles/minimal.nix")
    (modulesPath + "/profiles/installation-device.nix")
    (modulesPath + "/installer/cd-dvd/iso-image.nix")
  ];

  # ISO naming.
  isoImage.isoName = lib.mkForce "nixos-chill-penguin-${config.system.nixos.label}-${pkgs.stdenv.hostPlatform.system}.iso";

  # EFI booting
  isoImage.makeEfiBootable = true;
  isoImage.makeUsbBootable = true;

  # An installation media cannot tolerate a host config defined file
  # system layout on a fresh machine, before it has been formatted.
  swapDevices = lib.mkOverride 60 [ ];
  fileSystems = lib.mkOverride 60 config.lib.isoFileSystems;

  # can't legally be incorporated into the installer image
  hardware.asahi.extractPeripheralFirmware = false;

  isoImage.squashfsCompression = "zstd -Xcompression-level 6";

  # save space and compilation time.
  hardware.enableAllFirmware = lib.mkForce false;
  hardware.enableRedistributableFirmware = lib.mkForce false;
  services.pulseaudio.enable = false;
  hardware.asahi.setupAsahiSound = false;
  system.extraDependencies = lib.mkForce [ ];

  # bootspec generation is currently broken under cross-compilation
  boot.bootspec.enable = false;

  # avoid error that ZFS does not build against our kernel
  boot.supportedFilesystems.zfs = false;

  # Cross-compilation fixes (stolen from nixos-apple-silicon)
  nixpkgs.overlays =
    lib.optionals (config.nixpkgs.hostPlatform.system != config.nixpkgs.buildPlatform.system)
      [
        (final: prev: {
          libfido2 = prev.libfido2.override {
            withPcsclite = false;
          };
          openssh = prev.openssh.overrideAttrs (old: {
            doCheck = false;
          });
          util-linux = prev.util-linux.override {
            translateManpages = false;
          };
          libcap = prev.libcap.override {
            withGo = false;
          };
        })
      ];

  # avoids the need to cross-compile gobject introspection stuff
  security.polkit.enable = lib.mkForce false;
}
