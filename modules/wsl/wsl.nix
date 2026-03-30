{ pkgs, ... }:

{
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
