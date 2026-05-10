{ config, lib, pkgs, ... }:

let
  nixos-enter = pkgs.nixos-enter or config.system.build.nixos-enter;
  nixos-enter' = nixos-enter.overrideAttrs (_: {
    runtimeShell = "/bin/bash";
  });

  nixosWslRecovery = pkgs.writeScriptBin "nixos-wsl-recovery" ''
    #! /bin/sh
    if [ -f /etc/NIXOS ]; then
      echo "nixos-wsl-recovery should only be run from the WSL system distribution."
      echo "Example:"
      echo "    wsl --system --distribution NixOS --user root -- /nix/var/nix/profiles/system/bin/nixos-wsl-recovery"
      exit 1
    fi
    mount -o remount,rw /mnt/wslg/distro
    exec /mnt/wslg/distro/${nixos-enter'}/bin/nixos-enter --root /mnt/wslg/distro "$@"
  '';
in
{
  # WSL develop hosts run multiple flake-aware shells and agent sessions at
  # once. Letting the daemon use every reported core makes it easy to saturate
  # memory and leave new clients waiting on a busy daemon.
  nix.settings.max-jobs = lib.mkForce 8;
  nix.settings.cores = lib.mkDefault 4;

  services.resolved.enable = false;
  networking.useNetworkd = false;
  systemd.network.enable = false;

  wsl = {
    enable = true;
    interop.register = true;
    wslConf = {
      automount.enabled = true;
      interop.enabled = true;
      interop.appendWindowsPath = true;
    };
    docker-desktop.enable = true;
    extraBin = [
      { src = "${pkgs.coreutils}/bin/whoami"; }
    ];
  };

  ghostship.wsl.fhsShims = [
    {
      target = "/bin/sh";
      source = config.wsl.binShExe;
    }
    {
      target = "/bin/bash";
      source = "${pkgs.bashInteractive}/bin/bash";
    }
    {
      target = "/bin/mount";
      source = "${pkgs.util-linux}/bin/mount";
    }
    {
      target = "/bin/wslpath";
      source = "/init";
    }
    {
      target = "/bin/login";
      source = "${pkgs.shadow}/bin/login";
    }
    {
      target = "/bin/cat";
      source = "${pkgs.coreutils}/bin/cat";
    }
    {
      target = "/bin/whoami";
      source = "${pkgs.coreutils}/bin/whoami";
    }
    {
      target = "/bin/groupadd";
      source = "${pkgs.shadow}/bin/groupadd";
    }
    {
      target = "/bin/usermod";
      source = "${pkgs.shadow}/bin/usermod";
    }
    {
      target = "/bin/nixos-wsl-recovery";
      source = "${nixosWslRecovery}/bin/nixos-wsl-recovery";
      copy = true;
    }
    {
      target = "/usr/bin/env";
      source = "${pkgs.coreutils}/bin/env";
    }
    {
      target = "/usr/bin/bash";
      source = "${pkgs.bashInteractive}/bin/bash";
    }
    {
      target = "/usr/bin/sh";
      source = config.wsl.binShExe;
    }
    {
      target = "/usr/bin/bwrap";
      source = "${pkgs.bubblewrap}/bin/bwrap";
    }
    {
      target = "/usr/bin/node";
      source = "${pkgs.nodejs}/bin/node";
    }
    {
      target = "/usr/bin/npm";
      source = "${pkgs.nodejs}/bin/npm";
    }
    {
      target = "/usr/bin/npx";
      source = "${pkgs.nodejs}/bin/npx";
    }
    {
      target = "/usr/bin/gh";
      source = "${pkgs.gh}/bin/gh";
    }
    {
      target = "/usr/bin/starship";
      source = "${pkgs.starship}/bin/starship";
    }
  ];

  environment.variables.WSLENV = "USERPROFILE/p";
}
