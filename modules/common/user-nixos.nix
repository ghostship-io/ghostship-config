{ config, pkgs, lib, ... }:

let
  roles = config.ghostship.host.roles or { };
in

{
  # Global shell configuration
  programs.fish.enable = roles.develop or false;

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
    shell = if roles.develop or false then pkgs.fish else pkgs.bashInteractive;
    openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFh0VLGYtDCgU2MKtiHmHf8al1iq12zpFQR2g1yEpHkL owner@home.local"
    ];
  };

  # Sudo configuration
  security.sudo.wheelNeedsPassword = true;
  security.sudo.extraConfig = ''
    # Disable the sudo lecture (the "With great power comes great responsibility" warning)
    Defaults lecture="never"
  '' + lib.optionalString (roles.develop or false) ''
    # Share sudo auth across develop-host agent shells for up to 12 hours.
    Defaults timestamp_type=global
    Defaults timestamp_timeout=720
  '';

  users.groups.nixos.gid = 1000;
}
