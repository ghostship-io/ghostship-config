{ lib, pkgs, ... }:

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
    };
    docker-desktop.enable = true;
    extraBin = [
      { src = "${pkgs.coreutils}/bin/whoami"; }
    ];
  };

  environment.variables.WSLENV = "USERPROFILE/p";
}
