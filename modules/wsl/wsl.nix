{ lib, pkgs, ... }:

let
  wrappedNpm = pkgs.writeShellScriptBin "npm" ''
    exec ${pkgs.nodejs}/bin/npm "$@"
  '';
  wrappedNpx = pkgs.writeShellScriptBin "npx" ''
    exec ${pkgs.nodejs}/bin/npx "$@"
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
      # Keep envfs focused on Linux/FHS paths like /usr/bin/bash.
      interop.appendWindowsPath = false;
    };
    docker-desktop.enable = true;
    extraBin = [
      { src = "${pkgs.coreutils}/bin/whoami"; }
      { src = "${wrappedNpm}/bin/npm"; }
      { src = "${wrappedNpx}/bin/npx"; }
    ];
  };

  environment.variables.WSLENV = "USERPROFILE/p";
}
