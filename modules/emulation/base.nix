{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;
  packages = config.ghostship.emulation.internal.packages;
in
{
  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      nixpkgs.config.allowUnfreePredicate = pkg:
        let
          name = lib.getName pkg;
        in
        lib.hasPrefix "libretro-" name || builtins.elem name [
          "pico-8"
          "steam-run"
          "steam-unwrapped"
        ];

      users.groups.${cfg.group} = { };
      users.users.${cfg.user} = {
        isNormalUser = true;
        group = cfg.group;
        extraGroups = [ "audio" "input" "render" "video" "networkmanager" ];
        home = "/home/${cfg.user}";
        createHome = true;
      };

      boot.kernelParams = [ "amd_pstate=active" ];
      boot.kernelModules = [ "amdgpu" ];

      hardware.graphics = {
        enable = true;
        enable32Bit = true;
      };

      networking.networkmanager.enable = lib.mkDefault true;
      programs.gamemode.enable = true;
      services.libinput.enable = true;

      environment.sessionVariables = {
        ESDE_APPDATA_DIR = cfg.esde.appDataDir;
        BOOMER_EMULATION_DATA_ROOT = cfg.dataRoot;
        BOOMER_EMULATION_CONFIG_ROOT = cfg.configRoot;
        BOOMER_EMULATION_FAST_ROOT = "/fast/emulation";
        MESA_SHADER_CACHE_DIR = "/fast/emulation/cache/mesa-shaders";
        RADV_PERFTEST = "gpl";
      };

      environment.systemPackages = [
        packages.artBookNext
        packages.esdePackage
        packages.joypadAutoconfig
        packages.pico8Package
        packages.retroarchPackage
        packages.shaderCg
        packages.shaderGlsl
        packages.shaderSlang
        pkgs.bluez
        pkgs.bluez-tools
        pkgs.foot
        pkgs.gamemode
        pkgs.gamescope
        pkgs.jq
        pkgs.mangohud
        pkgs.mesa-demos
        pkgs.networkmanager
        pkgs.vkbasalt
        pkgs.vulkan-tools
        pkgs.winetricks
        packages.winePackage
      ]
      ++ builtins.attrValues config.ghostship.emulation.internal.scripts
      ++ emu.optionalPackages [
        "cemu"
        "dolphin-emu"
        "gzdoom"
        "joycond"
        "joycond-cemuhook"
        "lime3ds"
        "protontricks"
        "ryubing"
        "xemu"
      ]
      ++ lib.optional (packages.supermodelPackage != null) packages.supermodelPackage;

      systemd.tmpfiles.rules = [
        "d ${cfg.dataRoot} 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.romRoot} 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.biosRoot} 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.dataRoot}/saves 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.dataRoot}/states 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.dataRoot}/screenshots 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot} 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/controllers 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/display 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/emulators 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/retroarch 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/retroarch/shaders 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/retroarch/shaders-user 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.configRoot}/es-de 0755 ${cfg.user} ${cfg.group} -"
        "d ${cfg.dataRoot}/logs 0755 ${cfg.user} ${cfg.group} -"
        "d /run/ghostship-secrets 0755 root root -"
        "L+ /home/${cfg.user}/Emulation - - - - ${cfg.dataRoot}"
      ];
    }

    (lib.mkIf (cfg.romDisk.uuid != null) {
      fileSystems.${cfg.romRoot} = {
        device = "/dev/disk/by-uuid/${cfg.romDisk.uuid}";
        fsType = cfg.romDisk.fsType;
        options = cfg.romDisk.mountOptions;
      };
    })
  ]);
}
