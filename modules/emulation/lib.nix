{ config
, lib
, pkgs
, ...
}:

let
  cfg = config.ghostship.emulation;

  optionalPackage = name: lib.optional (builtins.hasAttr name pkgs) (builtins.getAttr name pkgs);
  optionalPackages = names: lib.concatMap optionalPackage names;
  n3dsEmulator =
    if builtins.hasAttr "azahar" pkgs then "azahar"
    else if builtins.hasAttr "lime3ds" pkgs then "lime3ds"
    else "retroarch-citra";

  xmlEscape =
    value:
    builtins.replaceStrings [ "&" "<" ">" "\"" "'" ] [ "&amp;" "&lt;" "&gt;" "&quot;" "&apos;" ] value;

  coreNames = [
    "fbneo"
    "mame"
    "fceumm"
    "mesen"
    "snes9x"
    "bsnes"
    "bsnes-hd"
    "genesis-plus-gx"
    "picodrive"
    "beetle-supergrafx"
    "beetle-pce-fast"
    "gambatte"
    "sameboy"
    "mgba"
    "beetle-ngp"
    "neocd"
    "beetle-vb"
    "beetle-psx-hw"
    "beetle-saturn"
    "flycast"
    "mupen64plus"
    "parallel-n64"
    "desmume"
    "melonds"
    "ppsspp"
    "pcsx2"
    "citra"
  ];

  commonRetroExtensions = ".7z .7Z .zip .ZIP .rar .RAR";
  discExtensions = ".bin .BIN .cue .CUE .iso .ISO .chd .CHD .m3u .M3U";

  romSystems = [
    {
      id = "fbneo";
      folder = "Arcade - Final Burn Neo (2019)";
      fullname = "Arcade - Final Burn Neo";
      platform = "arcade";
      theme = "arcade";
      emulator = "retroarch-fbneo";
      extensions = "${commonRetroExtensions} .fba .FBA";
      fixedAspect = "4:3";
    }
    {
      id = "model3";
      folder = "Arcade - Model 3 (1996)";
      fullname = "Sega Model 3";
      platform = "arcade";
      theme = "model3";
      emulator = "supermodel";
      extensions = ".zip .ZIP";
      fixedAspect = "4:3";
    }
    {
      id = "teknoparrot";
      folder = "Arcade - TeknoParrot (2017)";
      fullname = "TeknoParrot";
      platform = "arcade";
      theme = "teknoparrot";
      emulator = "teknoparrot";
      extensions = ".xml .XML";
      fixedAspect = "native";
    }
    {
      id = "xbox";
      folder = "Microsoft - Xbox (2001)";
      fullname = "Microsoft Xbox";
      platform = "xbox";
      theme = "xbox";
      emulator = "xemu";
      alternateEmulators = [
        {
          label = "xemu-hotkeys";
          emulator = "xemu-hotkeys";
        }
      ];
      extensions = ".xiso .XISO";
      fixedAspect = "16:9";
    }
    {
      id = "pcengine";
      folder = "NEC - PC Engine (1987)";
      fullname = "NEC PC Engine";
      platform = "pcengine";
      theme = "pcengine";
      emulator = "retroarch-beetle-supergrafx";
      extensions = "${commonRetroExtensions} .pce .PCE .sgx .SGX";
      fixedAspect = "4:3";
    }
    {
      id = "pcenginecd";
      folder = "NEC - PC Engine CD (1988)";
      fullname = "NEC PC Engine CD";
      platform = "pcenginecd";
      theme = "pcenginecd";
      emulator = "retroarch-beetle-pce-fast";
      extensions = "${commonRetroExtensions} ${discExtensions}";
      fixedAspect = "4:3";
    }
    {
      id = "gb";
      folder = "Nintendo - Game Boy (1989)";
      fullname = "Nintendo Game Boy";
      platform = "gb";
      theme = "gb";
      emulator = "retroarch-gambatte";
      extensions = "${commonRetroExtensions} .gb .GB";
      fixedAspect = "10:9";
    }
    {
      id = "gba";
      folder = "Nintendo - Game Boy Advance (2001)";
      fullname = "Nintendo Game Boy Advance";
      platform = "gba";
      theme = "gba";
      emulator = "retroarch-mgba";
      extensions = "${commonRetroExtensions} .gba .GBA";
      fixedAspect = "3:2";
    }
    {
      id = "gbc";
      folder = "Nintendo - Game Boy Color (1998)";
      fullname = "Nintendo Game Boy Color";
      platform = "gbc";
      theme = "gbc";
      emulator = "retroarch-gambatte";
      extensions = "${commonRetroExtensions} .gbc .GBC";
      fixedAspect = "10:9";
    }
    {
      id = "gc";
      folder = "Nintendo - GameCube (2001)";
      fullname = "Nintendo GameCube";
      platform = "gc";
      theme = "gc";
      emulator = "dolphin";
      extensions = "${commonRetroExtensions} ${discExtensions} .gcm .GCM .gcz .GCZ .rvz .RVZ .nkit.iso .NKIT.ISO";
      fixedAspect = "4:3";
    }
    {
      id = "n3ds";
      folder = "Nintendo - Nintendo 3DS (2011)";
      fullname = "Nintendo 3DS";
      platform = "n3ds";
      theme = "n3ds";
      emulator = n3dsEmulator;
      extensions = "${commonRetroExtensions} .3ds .3DS .3dsx .3DSX .cia .CIA .cxi .CXI";
      fixedAspect = "native";
    }
    {
      id = "n64";
      folder = "Nintendo - Nintendo 64 (1996)";
      fullname = "Nintendo 64";
      platform = "n64";
      theme = "n64";
      emulator = "retroarch-mupen64plus";
      extensions = "${commonRetroExtensions} .n64 .N64 .v64 .V64 .z64 .Z64";
      fixedAspect = "4:3";
    }
    {
      id = "nds";
      folder = "Nintendo - Nintendo DS (2004)";
      fullname = "Nintendo DS";
      platform = "nds";
      theme = "nds";
      emulator = "retroarch-desmume";
      extensions = "${commonRetroExtensions} .nds .NDS";
      fixedAspect = "native";
    }
    {
      id = "nes";
      folder = "Nintendo - Nintendo Entertainment System (1983)";
      fullname = "Nintendo Entertainment System";
      platform = "nes";
      theme = "nes";
      emulator = "retroarch-fceumm";
      extensions = "${commonRetroExtensions} .nes .NES .fds .FDS";
      fixedAspect = "4:3";
    }
    {
      id = "snes";
      folder = "Nintendo - Super Nintendo Entertainment System (1990)";
      fullname = "Super Nintendo Entertainment System";
      platform = "snes";
      theme = "snes";
      emulator = "retroarch-snes9x";
      extensions = "${commonRetroExtensions} .sfc .SFC .smc .SMC .bs .BS";
      fixedAspect = "4:3";
    }
    {
      id = "switch";
      folder = "Nintendo - Switch (2017)";
      fullname = "Nintendo Switch";
      platform = "switch";
      theme = "switch";
      emulator = "ryubing";
      extensions = ".nsp .NSP .xci .XCI .nca .NCA .nro .NRO";
      fixedAspect = "16:9";
    }
    {
      id = "virtualboy";
      folder = "Nintendo - Virtual Boy (1995)";
      fullname = "Nintendo Virtual Boy";
      platform = "virtualboy";
      theme = "virtualboy";
      emulator = "retroarch-beetle-vb";
      extensions = "${commonRetroExtensions} .vb .VB .vboy .VBOY";
      fixedAspect = "4:3";
    }
    {
      id = "wii";
      folder = "Nintendo - Wii (2006)";
      fullname = "Nintendo Wii";
      platform = "wii";
      theme = "wii";
      emulator = "dolphin";
      extensions = "${commonRetroExtensions} ${discExtensions} .wbfs .WBFS .rvz .RVZ .nkit.iso .NKIT.ISO .wad .WAD";
      fixedAspect = "16:9";
    }
    {
      id = "wiiu";
      folder = "Nintendo - Wii U (2012)";
      fullname = "Nintendo Wii U";
      platform = "wiiu";
      theme = "wiiu";
      emulator = "cemu";
      extensions = "${commonRetroExtensions} .wua .WUA .wud .WUD .wux .WUX .rpx .RPX";
      fixedAspect = "16:9";
    }
    {
      id = "neogeocd";
      folder = "SNK - Neo Geo CD (1994)";
      fullname = "SNK Neo Geo CD";
      platform = "neogeocd";
      theme = "neogeocd";
      emulator = "retroarch-neocd";
      extensions = "${commonRetroExtensions} ${discExtensions}";
      fixedAspect = "4:3";
    }
    {
      id = "ngpc";
      folder = "SNK - Neo Geo Pocket Color (1999)";
      fullname = "SNK Neo Geo Pocket Color";
      platform = "ngpc";
      theme = "ngpc";
      emulator = "retroarch-beetle-ngp";
      extensions = "${commonRetroExtensions} .ngp .NGP .ngc .NGC";
      fixedAspect = "20:19";
    }
    {
      id = "dreamcast";
      folder = "Sega - Dreamcast (1998)";
      fullname = "Sega Dreamcast";
      platform = "dreamcast";
      theme = "dreamcast";
      emulator = "retroarch-flycast";
      extensions = "${commonRetroExtensions} ${discExtensions} .gdi .GDI .cdi .CDI";
      fixedAspect = "4:3";
    }
    {
      id = "gamegear";
      folder = "Sega - Game Gear (1990)";
      fullname = "Sega Game Gear";
      platform = "gamegear";
      theme = "gamegear";
      emulator = "retroarch-genesis-plus-gx";
      extensions = "${commonRetroExtensions} .gg .GG";
      fixedAspect = "4:3";
    }
    {
      id = "genesis";
      folder = "Sega - Genesis (1988)";
      fullname = "Sega Genesis";
      platform = "genesis";
      theme = "genesis";
      emulator = "retroarch-genesis-plus-gx";
      extensions = "${commonRetroExtensions} .md .MD .gen .GEN .smd .SMD";
      fixedAspect = "4:3";
    }
    {
      id = "mastersystem";
      folder = "Sega - Master System (1985)";
      fullname = "Sega Master System";
      platform = "mastersystem";
      theme = "mastersystem";
      emulator = "retroarch-genesis-plus-gx";
      extensions = "${commonRetroExtensions} .sms .SMS";
      fixedAspect = "4:3";
    }
    {
      id = "saturn";
      folder = "Sega - Saturn (1994)";
      fullname = "Sega Saturn";
      platform = "saturn";
      theme = "saturn";
      emulator = "retroarch-beetle-saturn";
      extensions = "${commonRetroExtensions} ${discExtensions}";
      fixedAspect = "4:3";
    }
    {
      id = "segacd";
      folder = "Sega - Sega CD (1991)";
      fullname = "Sega CD";
      platform = "segacd";
      theme = "segacd";
      emulator = "retroarch-genesis-plus-gx";
      extensions = "${commonRetroExtensions} ${discExtensions}";
      fixedAspect = "4:3";
    }
    {
      id = "psx";
      folder = "Sony - PlayStation (1994)";
      fullname = "Sony PlayStation";
      platform = "psx";
      theme = "psx";
      emulator = "retroarch-beetle-psx-hw";
      extensions = "${commonRetroExtensions} ${discExtensions} .pbp .PBP";
      fixedAspect = "4:3";
    }
    {
      id = "ps2";
      folder = "Sony - PlayStation 2 (2000)";
      fullname = "Sony PlayStation 2";
      platform = "ps2";
      theme = "ps2";
      emulator = "pcsx2";
      extensions = "${commonRetroExtensions} ${discExtensions} .cso .CSO";
      fixedAspect = "16:9";
    }
    {
      id = "psp";
      folder = "Sony - PlayStation Portable (2004)";
      fullname = "Sony PlayStation Portable";
      platform = "psp";
      theme = "psp";
      emulator = "ppsspp";
      extensions = "${commonRetroExtensions} .iso .ISO .cso .CSO .pbp .PBP";
      fixedAspect = "16:9";
    }
  ];

  optionalSystems = [
    {
      id = "doom";
      folder = "Fantasy - GZDoom (2005)";
      fullname = "Doom";
      platform = "doom";
      theme = "doom";
      emulator = "gzdoom";
      extensions = ".wad .WAD .iwad .IWAD .pwad .PWAD .pk3 .PK3 .pk7 .PK7 .gzdoom .GZDOOM";
      fixedAspect = "native";
    }
    {
      id = "pico8";
      folder = "Fantasy - PICO-8 (2015)";
      fullname = "PICO-8";
      platform = "pico8";
      theme = "pico8";
      emulator = "pico8";
      alternateEmulators = [
        {
          label = "PICO-8 Hotkeys";
          emulator = "pico8-hotkeys";
        }
      ];
      extensions = ".png .PNG";
      fixedAspect = "4:3";
    }
  ];

  tools = [
    {
      file = "Bluetooth Settings.sh";
      target = "bluetooth-settings";
    }
    {
      file = "Wi-Fi Settings.sh";
      target = "wifi-settings";
    }
    {
      file = "Controller Maps.sh";
      target = "controller-maps";
    }
    {
      file = "Restart ES-DE.sh";
      target = "restart-esde";
    }
    {
      file = "Reboot.sh";
      target = "system-reboot";
    }
    {
      file = "Shutdown.sh";
      target = "system-shutdown";
    }
  ];

  scriptPath = lib.makeBinPath [
    pkgs.bash
    pkgs.bluez
    pkgs.bluez-tools
    pkgs.coreutils
    pkgs.findutils
    pkgs.gawk
    pkgs.gnugrep
    pkgs.gnused
    pkgs.jq
    pkgs.networkmanager
    pkgs.procps
    pkgs.systemd
    pkgs.util-linux
  ];
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.lib = {
      inherit
        commonRetroExtensions
        coreNames
        discExtensions
        n3dsEmulator
        optionalPackage
        optionalPackages
        optionalSystems
        romSystems
        scriptPath
        tools
        xmlEscape
        ;
      allSystems = romSystems ++ optionalSystems;
      allSystemsJson = builtins.toJSON (romSystems ++ optionalSystems);
      romSystemsJson = builtins.toJSON romSystems;
    };
  };
}
