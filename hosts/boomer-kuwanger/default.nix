{ pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ../../modules/common/default.nix
  ];

  # Hostname
  networking.hostName = "boomer-kuwanger";

  ghostship.host.roles = {
    server = true;
  };

  # Enable Hyprland
  programs.hyprland = {
    enable = true;
    xwayland.enable = true;
  };

  # Graphics (Mesa)
  hardware.graphics = {
    enable = true;
    enable32Bit = true;
  };

  # Fonts
  fonts.packages = with pkgs; [
    noto-fonts
    noto-fonts-cjk-sans
    noto-fonts-color-emoji
    liberation_ttf
    fira-code
    fira-code-symbols
    mplus-outline-fonts.githubRelease
    dina-font
    proggyfonts
    nerd-fonts.fira-code
    nerd-fonts.droid-sans-mono
  ];

  # Basic input settings
  services.libinput.enable = true;
  services.xserver.xkb = {
    layout = "us";
    variant = "";
  };

  # State version
  system.stateVersion = "25.11";
}
