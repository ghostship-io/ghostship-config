{ config, pkgs, lib, ... }:

{
  # Global shell configuration
  programs.fish.enable = true;

  # Allow manual password changes to persist
  users.mutableUsers = true;

  # Lock the root account system-wide to prevent direct password logins
  users.users.root = {
    hashedPassword = "!";
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFh0VLGYtDCgU2MKtiHmHf8al1iq12zpFQR2g1yEpHkL owner@home.local"
    ];
  };

  # Common user definition for 'nixos'
  users.users.nixos = {
    isNormalUser = true;
    uid = 1000;
    group = "nixos";
    description = "nixos";
    extraGroups = [ "wheel" "networkmanager" ];
    shell = pkgs.fish;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFh0VLGYtDCgU2MKtiHmHf8al1iq12zpFQR2g1yEpHkL owner@home.local"
    ];
  };

  # Sudo configuration
  security.sudo.wheelNeedsPassword = true;
  security.sudo.extraConfig = ''
    # Disable the sudo lecture (the "With great power comes great responsibility" warning)
    Defaults lecture="never"
    # Require password re-authentication every 8 hours
    Defaults timestamp_timeout=480
  '';

  users.groups.nixos.gid = 1000;
}
