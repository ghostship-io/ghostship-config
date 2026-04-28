{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  inherit (lib) mkEnableOption mkIf mkOption types;

  optionalPackage = name: lib.optional (builtins.hasAttr name pkgs) (builtins.getAttr name pkgs);
  optionalPackages = names: lib.concatMap optionalPackage names;
  n3dsEmulator = if builtins.hasAttr "lime3ds" pkgs then "lime3ds" else "retroarch-citra";
  winePackage =
    if pkgs ? wineWowPackages && pkgs.wineWowPackages ? staging then pkgs.wineWowPackages.staging
    else if pkgs ? wineWow64Packages && pkgs.wineWow64Packages ? staging then pkgs.wineWow64Packages.staging
    else pkgs.wine;
  supermodelPackage =
    if pkgs ? supermodel then
      pkgs.supermodel.overrideAttrs
        (old: {
          postPatch = (old.postPatch or "") + ''
            if [ -f Src/Game.h ] && ! grep -q '<cstdint>' Src/Game.h; then
              sed -i '1i #include <cstdint>' Src/Game.h
            fi
          '';
        })
    else
      null;

  xmlEscape = value:
    builtins.replaceStrings [ "&" "<" ">" "\"" "'" ] [ "&amp;" "&lt;" "&gt;" "&quot;" "&apos;" ] value;

  coreNames = [
    "fbneo"
    "mame"
    "mesen"
    "snes9x"
    "bsnes"
    "bsnes-hd"
    "genesis-plus-gx"
    "picodrive"
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
    "melonds"
    "ppsspp"
    "pcsx2"
    "citra"
  ];

  retroarchPackage = pkgs.retroarch.withCores (cores:
    lib.filter (core: core != null) (map (name: cores.${name} or null) coreNames));

  emptyJoypadAutoconfig = pkgs.runCommand "empty-retroarch-joypad-autoconfig" { } ''
    mkdir -p $out/share/libretro/autoconfig
  '';

  joypadAutoconfig =
    if pkgs ? retroarch-joypad-autoconfig
    then pkgs.retroarch-joypad-autoconfig
    else emptyJoypadAutoconfig;

  esdePackage = pkgs.appimageTools.wrapType2 rec {
    pname = "es-de";
    version = "3.4.1";
    src = pkgs.fetchurl {
      url = "https://gitlab.com/es-de/emulationstation-de/-/package_files/288156961/download";
      name = "ES-DE_x64.AppImage";
      sha256 = "109mfa3aag6x4gf08326cbgs09dl403ygvaqm8yicmcdfd6s8q9w";
    };
    extraInstallCommands = ''
      if [ -e "$out/bin/es-de-${version}" ]; then
        mv "$out/bin/es-de-${version}" "$out/bin/es-de"
      fi
    '';
  };

  artBookNext = pkgs.stdenvNoCC.mkDerivation {
    pname = "art-book-next-es-de";
    version = "0-unstable-2026-04-28";
    src = pkgs.fetchFromGitHub {
      owner = "anthonycaccese";
      repo = "art-book-next-es-de";
      rev = "d772d07109701d9bd7c9fda305bfef6601105ab8";
      sha256 = "0ndf4fgy046qndhl5dzryl1m0zndyq5n3cla3ydnzdrrb1mwn9zp";
    };
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/share/es-de/themes/art-book-next-es-de"
      cp -R . "$out/share/es-de/themes/art-book-next-es-de/"
      runHook postInstall
    '';
  };

  shaderSlang = pkgs.stdenvNoCC.mkDerivation {
    pname = "boomer-libretro-shaders-slang";
    version = "0-unstable-2026-04-28";
    src = pkgs.fetchFromGitHub {
      owner = "libretro";
      repo = "slang-shaders";
      rev = "cc71b5eff24a962bd055a92d2032f806635fdf97";
      sha256 = "191x3aylm2p1i4clr6i592p6fnrw2z4718mlnmlsgb60jlgvmq9x";
    };
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/share/libretro/shaders_slang"
      cp -R . "$out/share/libretro/shaders_slang/"
      runHook postInstall
    '';
  };

  shaderGlsl = pkgs.stdenvNoCC.mkDerivation {
    pname = "boomer-libretro-shaders-glsl";
    version = "0-unstable-2026-04-28";
    src = pkgs.fetchFromGitHub {
      owner = "libretro";
      repo = "glsl-shaders";
      rev = "2f0979fc71aec8701c889c32db40dde1e24258ac";
      sha256 = "00253q6alkdpgn8szdzc6vzk4wqz52zvx8h51pc8p0abff6fx2zm";
    };
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/share/libretro/shaders_glsl"
      cp -R . "$out/share/libretro/shaders_glsl/"
      runHook postInstall
    '';
  };

  shaderCg = pkgs.stdenvNoCC.mkDerivation {
    pname = "boomer-libretro-shaders-cg";
    version = "0-unstable-2026-04-28";
    src = pkgs.fetchFromGitHub {
      owner = "libretro";
      repo = "common-shaders";
      rev = "9c0d839a19651dffc9898da7673574a20fb39415";
      sha256 = "06l362fi3cfq6xxc5pxzy1dhw95l8mgrqpahnwhijayp9fjhws0d";
    };
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/share/libretro/shaders_cg"
      cp -R . "$out/share/libretro/shaders_cg/"
      runHook postInstall
    '';
  };

  pico8Package = pkgs.stdenvNoCC.mkDerivation {
    pname = "pico-8";
    version = "0.2.7";
    src = pkgs.requireFile {
      name = "pico-8_0.2.7_amd64.zip";
      sha256 = "1alyii0bc9r9j2519q3jhxn8xazrcffy0kl8k07mnn208y2wxwpd";
      url = "file:///mnt/c/Users/the owner/Downloads/pico-8_0.2.7_amd64.zip";
    };
    nativeBuildInputs = [ pkgs.makeWrapper pkgs.unzip ];
    unpackPhase = ''
      unzip "$src"
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p "$out/opt/pico-8" "$out/bin"
      cp -R pico-8/* "$out/opt/pico-8/"
      chmod +x "$out/opt/pico-8/pico8" "$out/opt/pico-8/pico8_dyn" || true
      makeWrapper ${pkgs.steam-run}/bin/steam-run "$out/bin/pico8" \
        --add-flags "$out/opt/pico-8/pico8"
      runHook postInstall
    '';
  };

  commonRetroExtensions = ".7z .7Z .zip .ZIP .rar .RAR";
  discExtensions = ".bin .BIN .cue .CUE .iso .ISO .chd .CHD .m3u .M3U";

  romSystems = [
    { id = "fbneo"; folder = "Arcade - Final Burn Neo (2019)"; fullname = "Arcade - Final Burn Neo"; platform = "arcade"; theme = "arcade"; emulator = "retroarch-fbneo"; extensions = "${commonRetroExtensions} .fba .FBA"; }
    { id = "teknoparrot"; folder = "Arcade - TeknoParrot (2017)"; fullname = "Arcade - TeknoParrot"; platform = "arcade"; theme = "arcade"; emulator = "teknoparrot"; extensions = ".xml .XML .lnk .LNK .exe .EXE .bat .BAT .cmd .CMD .tp .TP"; }
    { id = "xbox"; folder = "Microsoft - Xbox (2001)"; fullname = "Microsoft Xbox"; platform = "xbox"; theme = "xbox"; emulator = "xemu"; extensions = "${commonRetroExtensions} ${discExtensions} .xbe .XBE"; }
    { id = "pcengine"; folder = "NEC - PC Engine (1987)"; fullname = "NEC PC Engine"; platform = "pcengine"; theme = "pcengine"; emulator = "retroarch-beetle-pce-fast"; extensions = "${commonRetroExtensions} .pce .PCE .sgx .SGX"; }
    { id = "pcenginecd"; folder = "NEC - PC Engine CD (1988)"; fullname = "NEC PC Engine CD"; platform = "pcenginecd"; theme = "pcenginecd"; emulator = "retroarch-beetle-pce-fast"; extensions = "${commonRetroExtensions} ${discExtensions}"; }
    { id = "gb"; folder = "Nintendo - Game Boy (1989)"; fullname = "Nintendo Game Boy"; platform = "gb"; theme = "gb"; emulator = "retroarch-gambatte"; extensions = "${commonRetroExtensions} .gb .GB"; }
    { id = "gba"; folder = "Nintendo - Game Boy Advance (2001)"; fullname = "Nintendo Game Boy Advance"; platform = "gba"; theme = "gba"; emulator = "retroarch-mgba"; extensions = "${commonRetroExtensions} .gba .GBA"; }
    { id = "gbc"; folder = "Nintendo - Game Boy Color (1998)"; fullname = "Nintendo Game Boy Color"; platform = "gbc"; theme = "gbc"; emulator = "retroarch-gambatte"; extensions = "${commonRetroExtensions} .gbc .GBC"; }
    { id = "gc"; folder = "Nintendo - GameCube (2001)"; fullname = "Nintendo GameCube"; platform = "gc"; theme = "gc"; emulator = "dolphin"; extensions = "${commonRetroExtensions} ${discExtensions} .gcm .GCM .gcz .GCZ .rvz .RVZ .nkit.iso .NKIT.ISO"; }
    { id = "n3ds"; folder = "Nintendo - Nintendo 3DS (2011)"; fullname = "Nintendo 3DS"; platform = "n3ds"; theme = "n3ds"; emulator = n3dsEmulator; extensions = "${commonRetroExtensions} .3ds .3DS .3dsx .3DSX .cia .CIA .cxi .CXI"; }
    { id = "n64"; folder = "Nintendo - Nintendo 64 (1996)"; fullname = "Nintendo 64"; platform = "n64"; theme = "n64"; emulator = "retroarch-mupen64plus"; extensions = "${commonRetroExtensions} .n64 .N64 .v64 .V64 .z64 .Z64"; }
    { id = "nds"; folder = "Nintendo - Nintendo DS (2004)"; fullname = "Nintendo DS"; platform = "nds"; theme = "nds"; emulator = "retroarch-melonds"; extensions = "${commonRetroExtensions} .nds .NDS"; }
    { id = "nes"; folder = "Nintendo - Nintendo Entertainment System (1983)"; fullname = "Nintendo Entertainment System"; platform = "nes"; theme = "nes"; emulator = "retroarch-mesen"; extensions = "${commonRetroExtensions} .nes .NES .fds .FDS"; }
    { id = "snes"; folder = "Nintendo - Super Nintendo Entertainment System (1990)"; fullname = "Super Nintendo Entertainment System"; platform = "snes"; theme = "snes"; emulator = "retroarch-snes9x"; extensions = "${commonRetroExtensions} .sfc .SFC .smc .SMC .bs .BS"; }
    { id = "switch"; folder = "Nintendo - Switch (2017)"; fullname = "Nintendo Switch"; platform = "switch"; theme = "switch"; emulator = "ryubing"; extensions = ".nsp .NSP .xci .XCI .nca .NCA .nro .NRO"; }
    { id = "virtualboy"; folder = "Nintendo - Virtual Boy (1995)"; fullname = "Nintendo Virtual Boy"; platform = "virtualboy"; theme = "virtualboy"; emulator = "retroarch-beetle-vb"; extensions = "${commonRetroExtensions} .vb .VB .vboy .VBOY"; }
    { id = "wii"; folder = "Nintendo - Wii (2006)"; fullname = "Nintendo Wii"; platform = "wii"; theme = "wii"; emulator = "dolphin"; extensions = "${commonRetroExtensions} ${discExtensions} .wbfs .WBFS .rvz .RVZ .nkit.iso .NKIT.ISO"; }
    { id = "wiiu"; folder = "Nintendo - Wii U (2012)"; fullname = "Nintendo Wii U"; platform = "wiiu"; theme = "wiiu"; emulator = "cemu"; extensions = "${commonRetroExtensions} .wua .WUA .wud .WUD .wux .WUX .rpx .RPX"; }
    { id = "neogeocd"; folder = "SNK - Neo Geo CD (1994)"; fullname = "SNK Neo Geo CD"; platform = "neogeocd"; theme = "neogeocd"; emulator = "retroarch-neocd"; extensions = "${commonRetroExtensions} ${discExtensions}"; }
    { id = "ngpc"; folder = "SNK - Neo Geo Pocket Color (1999)"; fullname = "SNK Neo Geo Pocket Color"; platform = "ngpc"; theme = "ngpc"; emulator = "retroarch-beetle-ngp"; extensions = "${commonRetroExtensions} .ngp .NGP .ngc .NGC"; }
    { id = "dreamcast"; folder = "Sega - Dreamcast (1998)"; fullname = "Sega Dreamcast"; platform = "dreamcast"; theme = "dreamcast"; emulator = "retroarch-flycast"; extensions = "${commonRetroExtensions} ${discExtensions} .gdi .GDI .cdi .CDI"; }
    { id = "gamegear"; folder = "Sega - Game Gear (1990)"; fullname = "Sega Game Gear"; platform = "gamegear"; theme = "gamegear"; emulator = "retroarch-genesis-plus-gx"; extensions = "${commonRetroExtensions} .gg .GG"; }
    { id = "genesis"; folder = "Sega - Genesis (1988)"; fullname = "Sega Genesis"; platform = "genesis"; theme = "genesis"; emulator = "retroarch-genesis-plus-gx"; extensions = "${commonRetroExtensions} .md .MD .gen .GEN .smd .SMD"; }
    { id = "mastersystem"; folder = "Sega - Master System (1985)"; fullname = "Sega Master System"; platform = "mastersystem"; theme = "mastersystem"; emulator = "retroarch-genesis-plus-gx"; extensions = "${commonRetroExtensions} .sms .SMS"; }
    { id = "saturn"; folder = "Sega - Saturn (1994)"; fullname = "Sega Saturn"; platform = "saturn"; theme = "saturn"; emulator = "retroarch-beetle-saturn"; extensions = "${commonRetroExtensions} ${discExtensions}"; }
    { id = "segacd"; folder = "Sega - Sega CD (1991)"; fullname = "Sega CD"; platform = "segacd"; theme = "segacd"; emulator = "retroarch-genesis-plus-gx"; extensions = "${commonRetroExtensions} ${discExtensions}"; }
    { id = "psx"; folder = "Sony - PlayStation (1994)"; fullname = "Sony PlayStation"; platform = "psx"; theme = "psx"; emulator = "retroarch-beetle-psx-hw"; extensions = "${commonRetroExtensions} ${discExtensions} .pbp .PBP"; }
    { id = "ps2"; folder = "Sony - PlayStation 2 (2000)"; fullname = "Sony PlayStation 2"; platform = "ps2"; theme = "ps2"; emulator = "retroarch-pcsx2"; extensions = "${commonRetroExtensions} ${discExtensions} .cso .CSO"; }
    { id = "psp"; folder = "Sony - PlayStation Portable (2004)"; fullname = "Sony PlayStation Portable"; platform = "psp"; theme = "psp"; emulator = "retroarch-ppsspp"; extensions = "${commonRetroExtensions} .iso .ISO .cso .CSO .pbp .PBP"; }
  ];

  optionalSystems = [
    { id = "model3"; folder = "Sega - Model 3 (1996)"; fullname = "Sega Model 3"; platform = "arcade"; theme = "arcade"; emulator = "supermodel"; extensions = "${commonRetroExtensions} .bin .BIN"; }
    { id = "doom"; folder = "Ports - Doom"; fullname = "Doom"; platform = "doom"; theme = "doom"; emulator = "gzdoom"; extensions = ".wad .WAD .iwad .IWAD .pk3 .PK3 .pk7 .PK7"; }
    { id = "pico8"; folder = "PICO-8 (2015)"; fullname = "PICO-8"; platform = "pico8"; theme = "pico8"; emulator = "pico8"; extensions = ".p8 .P8 .p8.png .P8.PNG"; }
  ];

  allSystems = romSystems ++ optionalSystems;
  romSystemsJson = builtins.toJSON romSystems;
  allSystemsJson = builtins.toJSON allSystems;

  mkSystemXml = system: ''
    <system>
      <name>${xmlEscape system.id}</name>
      <fullname>${xmlEscape system.fullname}</fullname>
      <path>${xmlEscape "${cfg.romRoot}/${system.folder}"}</path>
      <extension>${xmlEscape system.extensions}</extension>
      <command>boomer-run-emulator ${xmlEscape system.id} ${xmlEscape system.emulator} %ROM%</command>
      <platform>${xmlEscape system.platform}</platform>
      <theme>${xmlEscape system.theme}</theme>
    </system>'';

  tools = [
    { file = "Wi-Fi Status.sh"; target = "boomer-wifi-status"; }
    { file = "Wi-Fi Connect.sh"; target = "boomer-wifi-connect"; }
    { file = "Bluetooth Status.sh"; target = "boomer-bluetooth-status"; }
    { file = "Bluetooth Pair Controller.sh"; target = "boomer-bluetooth-pair-controller"; }
    { file = "Bluetooth Reconnect Controllers.sh"; target = "boomer-bluetooth-reconnect-controllers"; }
    { file = "Player Assignment.sh"; target = "boomer-player-assignment"; }
    { file = "Display Profile Test.sh"; target = "boomer-display-profile-tool"; }
    { file = "Display Profile Override.sh"; target = "boomer-display-profile-override"; }
    { file = "RetroArch Core Status.sh"; target = "boomer-retroarch-core-status"; }
    { file = "RetroArch Graphics Profiles.sh"; target = "boomer-retroarch-graphics-profiles"; }
    { file = "RetroArch Shader Profiles.sh"; target = "boomer-retroarch-shader-profiles"; }
    { file = "ES-DE Scraper Status.sh"; target = "boomer-esde-scraper-status"; }
    { file = "ES-DE Scrape Missing Media.sh"; target = "boomer-esde-scrape-missing-media"; }
    { file = "Restart ES-DE.sh"; target = "boomer-restart-esde"; }
    { file = "Shutdown.sh"; target = "boomer-shutdown"; }
    { file = "Reboot.sh"; target = "boomer-reboot"; }
  ];

  esSystemsXml = pkgs.writeText "boomer-es-systems.xml" ''
    <?xml version="1.0"?>
    <systemList>
    ${lib.concatMapStringsSep "\n" mkSystemXml allSystems}
      <system>
        <name>tools</name>
        <fullname>Tools</fullname>
        <path>${xmlEscape "${cfg.dataRoot}/tools"}</path>
        <extension>.sh .SH</extension>
        <command>%ROM%</command>
        <platform>tools</platform>
        <theme>tools</theme>
      </system>
    </systemList>
  '';

  esFindRulesXml = pkgs.writeText "boomer-es-find-rules.xml" ''
    <?xml version="1.0"?>
    <ruleList>
      <emulator name="BOOMER_WRAPPER">
        <rule type="systempath">
          <entry>boomer-run-emulator</entry>
        </rule>
      </emulator>
      <emulator name="RETROARCH">
        <rule type="systempath">
          <entry>${retroarchPackage}/bin/retroarch</entry>
        </rule>
      </emulator>
      <emulator name="GAMESCOPE">
        <rule type="systempath">
          <entry>${pkgs.gamescope}/bin/gamescope</entry>
        </rule>
      </emulator>
    </ruleList>
  '';

  esSettingsXml = pkgs.writeText "boomer-es-settings.xml" ''
    <?xml version="1.0"?>
    <settings>
      <string name="ThemeSet" value="art-book-next-es-de" />
      <string name="Scraper" value="screenscraper" />
      <string name="ScraperRegion" value="na" />
      <string name="ScraperLanguage" value="en" />
      <string name="MediaDirectory" value="${xmlEscape "${cfg.esde.appDataDir}/downloaded_media"}" />
      <bool name="ScraperUseAccountScreenScraper" value="true" />
      <bool name="ScrapeGameNames" value="true" />
      <bool name="ScrapeRatings" value="true" />
      <bool name="ScrapeMetadata" value="true" />
      <bool name="ScrapeVideos" value="true" />
      <bool name="ScrapeScreenshots" value="true" />
      <bool name="ScrapeCovers" value="true" />
      <bool name="ScrapeMarquees" value="true" />
      <bool name="MiximageGenerate" value="true" />
      <bool name="MiximageIncludeMarquee" value="true" />
      <bool name="MiximageIncludeBox" value="true" />
      <bool name="MiximageIncludePhysicalMedia" value="true" />
      <bool name="ScraperSearchFileHash" value="true" />
      <bool name="ScraperInteractive" value="false" />
      <bool name="ScraperSemiautomatic" value="true" />
      <bool name="ScraperRegionFallback" value="true" />
      <bool name="Debug" value="false" />
      <bool name="CheckForUpdates" value="false" />
    </settings>
  '';

  retroarchCfg = pkgs.writeText "boomer-retroarch.cfg" ''
    video_driver = "vulkan"
    audio_driver = "pipewire"
    input_driver = "udev"
    menu_driver = "ozone"
    video_fullscreen = "true"
    video_vsync = "true"
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__GDV__DREZ-VIEWPORT.slangp"
    video_shader_dir = "${cfg.configRoot}/retroarch/shaders"
    libretro_directory = "${retroarchPackage}/lib/retroarch/cores"
    libretro_info_path = "${retroarchPackage}/share/libretro/info"
    system_directory = "${cfg.biosRoot}"
    savefile_directory = "${cfg.dataRoot}/saves"
    savestate_directory = "${cfg.dataRoot}/states"
    screenshot_directory = "${cfg.dataRoot}/screenshots"
    input_autodetect_enable = "true"
    joypad_autoconfig_dir = "${joypadAutoconfig}/share/libretro/autoconfig"
    input_menu_toggle_gamepad_combo = "3"
    input_enable_hotkey_btn = "8"
    input_menu_toggle_btn = "3"
    input_exit_emulator_btn = "9"
    input_save_state_btn = "5"
    input_load_state_btn = "4"
    config_save_on_exit = "false"
    log_verbosity = "true"
    log_to_file = "true"
    log_dir = "${cfg.dataRoot}/logs/retroarch"
    video_smooth = "false"
    video_scale_integer = "false"
    video_aspect_ratio_auto = "true"
    run_ahead_enabled = "false"
    threaded_video = "false"
    auto_remaps_enable = "true"
    remap_directory = "${cfg.configRoot}/retroarch/remaps"
    core_options_path = "${cfg.configRoot}/retroarch/core-options.cfg"
  '';

  retroarchCoreOptions = pkgs.writeText "boomer-retroarch-core-options.cfg" ''
    fbneo-allow-patched-romsets = "enabled"
    beetle_psx_hw_renderer = "hardware_vk"
    beetle_psx_hw_pgxp_mode = "memory + CPU"
    beetle_psx_hw_internal_resolution = "4x"
    beetle_saturn_virtuagun_crosshair = "Cross"
    mupen64plus-rdp-plugin = "parallel"
    mupen64plus-cpucore = "dynamic_recompiler"
    parallel-n64-gfxplugin = "parallel"
    melonds_boot_directly = "enabled"
    ppsspp_internal_resolution = "4"
    pcsx2_renderer = "Vulkan"
    pcsx2_upscale_multiplier = "3"
    flycast_renderer = "vulkan"
  '';

  retroarchMegabezelProfile = pkgs.writeText "boomer-megabezel-auto.cfg" ''
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__GDV__DREZ-VIEWPORT.slangp"
  '';

  retroarchPotatoProfile = pkgs.writeText "boomer-megabezel-potato.cfg" ''
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__5__POTATO__GDV__DREZ-VIEWPORT.slangp"
  '';

  retroarchPassthroughProfile = pkgs.writeText "boomer-megabezel-passthrough.cfg" ''
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/bezel/Mega_Bezel/Presets/Base_CRT_Presets_DREZ/MBZ__3__STD__PASSTHROUGH__DREZ-VIEWPORT.slangp"
  '';

  retroarchSharpProfile = pkgs.writeText "boomer-sharp-clean.cfg" ''
    video_shader_enable = "true"
    video_shader = "${cfg.configRoot}/retroarch/shaders/shaders_slang/interpolation/sharp-bilinear.slangp"
  '';

  retroarchIntegerProfile = pkgs.writeText "boomer-integer-raw.cfg" ''
    video_shader_enable = "false"
    video_scale_integer = "true"
    video_smooth = "false"
  '';

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

  boomerDisplayProfile = pkgs.writeShellScriptBin "boomer-display-profile" ''
    set -euo pipefail
    export PATH=${scriptPath}:$PATH

    width="''${BOOMER_DISPLAY_WIDTH:-}"
    height="''${BOOMER_DISPLAY_HEIGHT:-}"
    refresh="''${BOOMER_DISPLAY_REFRESH:-60}"

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v wlr-randr >/dev/null 2>&1; then
        mode="$(wlr-randr 2>/dev/null | awk '/^[^ ]/{out=$1} /current/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          rest="''${mode#*x}"
          height="''${rest%@*}"
          if printf '%s' "$rest" | grep -q '@'; then
            refresh="''${rest#*@}"
          fi
        fi
      fi
    fi

    if [ -z "$width" ] || [ -z "$height" ]; then
      if command -v xrandr >/dev/null 2>&1; then
        mode="$(xrandr --current 2>/dev/null | awk '/ connected/{out=$1} /\*/{print $1; exit}' || true)"
        if [ -n "$mode" ]; then
          width="''${mode%x*}"
          height="''${mode#*x}"
        fi
      fi
    fi

    width="''${width:-1920}"
    height="''${height:-1080}"
    aspect="$(awk -v w="$width" -v h="$height" 'BEGIN { if (h == 0) h = 1; printf "%.3f", w / h }')"
    class="$(awk -v a="$aspect" 'BEGIN { if (a > 2.2) print "super-ultrawide"; else if (a > 1.9) print "ultrawide"; else if (a > 1.65) print "widescreen"; else print "standard"; }')"
    heavy="''${BOOMER_EMULATOR_HEAVY:-0}"
    render_width="$width"
    render_height="$height"
    fsr=false
    fsr_sharpness="5"
    scale_mode="native"

    case "''${width}x''${height}" in
      3840x2160|5120x2160)
        if [ "$heavy" = "1" ]; then render_width=2954; render_height=1662; fsr=true; fi
        ;;
      3440x1440)
        if [ "$heavy" = "1" ]; then render_width=2646; render_height=1108; fsr=true; fi
        ;;
      3840x1600)
        if [ "$heavy" = "1" ]; then render_width=2954; render_height=1231; fsr=true; fi
        ;;
      5120x1440)
        if [ "$heavy" = "1" ]; then render_width=3840; render_height=1080; fsr=true; fi
        ;;
      7680x4320)
        render_width=3840; render_height=2160; fsr=true
        ;;
      2560x1440|2560x1600)
        if [ "$heavy" = "1" ]; then render_width=1920; render_height=1080; fsr=true; fi
        ;;
      1920x1080|1920x1200|1280x720)
        fsr=false
        ;;
      *)
        if [ "$heavy" = "1" ] && [ "$width" -gt 1920 ]; then
          render_width="$(awk -v w="$width" 'BEGIN { printf "%d", w * 0.77 }')"
          render_height="$(awk -v h="$height" 'BEGIN { printf "%d", h * 0.77 }')"
          fsr=true
        fi
        ;;
    esac

    if [ "''${BOOMER_FORCE_FSR:-0}" = "1" ]; then fsr=true; fi
    if [ "''${BOOMER_DISABLE_FSR:-0}" = "1" ]; then fsr=false; render_width="$width"; render_height="$height"; fi
    if [ -n "''${BOOMER_RENDER_SIZE:-}" ] && printf '%s' "$BOOMER_RENDER_SIZE" | grep -Eq '^[0-9]+x[0-9]+$'; then
      render_width="''${BOOMER_RENDER_SIZE%x*}"
      render_height="''${BOOMER_RENDER_SIZE#*x}"
      if [ "$render_width" != "$width" ] || [ "$render_height" != "$height" ]; then fsr=true; fi
    fi

    if [ "$render_width" = "$width" ] && [ "$render_height" = "$height" ]; then fsr=false; fi

    if [ "''${1:-}" = "gamescope-args" ]; then
      args=(-f -e -W "$width" -H "$height" -w "$render_width" -h "$render_height")
      if [ "$fsr" = true ]; then args+=(-F fsr --fsr-sharpness "$fsr_sharpness"); fi
      printf '%q ' "''${args[@]}"
      printf '\n'
      exit 0
    fi

    jq -n \
      --argjson output_width "$width" \
      --argjson output_height "$height" \
      --arg refresh "$refresh" \
      --arg aspect "$aspect" \
      --arg class "$class" \
      --argjson render_width "$render_width" \
      --argjson render_height "$render_height" \
      --argjson fsr "$fsr" \
      --arg fsr_sharpness "$fsr_sharpness" \
      --arg scale_mode "$scale_mode" \
      '{output_width:$output_width, output_height:$output_height, refresh:$refresh, aspect:($aspect|tonumber), class:$class, render_width:$render_width, render_height:$render_height, fsr:$fsr, fsr_sharpness:($fsr_sharpness|tonumber), scale_mode:$scale_mode}'
  '';

  boomerRunEmulator = pkgs.writeShellScriptBin "boomer-run-emulator" ''
    set -euo pipefail
    export PATH=${scriptPath}:${lib.makeBinPath ([
      retroarchPackage
      pkgs.gamescope
      pkgs.gamemode
      pkgs.mangohud
      pico8Package
      winePackage
    ] ++ optionalPackages [
      "dolphin-emu"
      "cemu"
      "xemu"
      "ryubing"
      "lime3ds"
      "gzdoom"
    ] ++ lib.optional (supermodelPackage != null) supermodelPackage)}:$PATH

    if [ "$#" -lt 3 ]; then
      echo "Usage: boomer-run-emulator <system-id> <emulator-id> <rom-path>" >&2
      exit 64
    fi

    system_id="$1"
    emulator_id="$2"
    rom_path="$3"
    log_dir="${cfg.dataRoot}/logs/launches"
    mkdir -p "$log_dir"
    log_file="$log_dir/$(date -u +%Y%m%dT%H%M%SZ)-$system_id.jsonl"

    log_event() {
      jq -nc --arg time "$(date -u +%FT%TZ)" --arg event "$1" --arg system "$system_id" --arg emulator "$emulator_id" --arg rom "$rom_path" --arg message "''${2:-}" \
        '{time:$time,event:$event,system:$system,emulator:$emulator,rom:$rom,message:$message}' >>"$log_file"
    }

    core_file_for() {
      case "$1" in
        retroarch-fbneo) echo fbneo_libretro.so ;;
        retroarch-mame) echo mame_libretro.so ;;
        retroarch-mesen) echo mesen_libretro.so ;;
        retroarch-snes9x) echo snes9x_libretro.so ;;
        retroarch-bsnes) echo bsnes_libretro.so ;;
        retroarch-bsnes-hd) echo bsnes_hd_beta_libretro.so ;;
        retroarch-genesis-plus-gx) echo genesis_plus_gx_libretro.so ;;
        retroarch-picodrive) echo picodrive_libretro.so ;;
        retroarch-beetle-pce-fast) echo mednafen_pce_fast_libretro.so ;;
        retroarch-gambatte) echo gambatte_libretro.so ;;
        retroarch-sameboy) echo sameboy_libretro.so ;;
        retroarch-mgba) echo mgba_libretro.so ;;
        retroarch-beetle-ngp) echo mednafen_ngp_libretro.so ;;
        retroarch-neocd) echo neocd_libretro.so ;;
        retroarch-beetle-vb) echo mednafen_vb_libretro.so ;;
        retroarch-beetle-psx-hw) echo mednafen_psx_hw_libretro.so ;;
        retroarch-beetle-saturn) echo mednafen_saturn_libretro.so ;;
        retroarch-flycast) echo flycast_libretro.so ;;
        retroarch-mupen64plus) echo mupen64plus_next_libretro.so ;;
        retroarch-parallel-n64) echo parallel_n64_libretro.so ;;
        retroarch-melonds) echo melondsds_libretro.so ;;
        retroarch-ppsspp) echo ppsspp_libretro.so ;;
        retroarch-pcsx2) echo pcsx2_libretro.so ;;
        retroarch-citra) echo citra_libretro.so ;;
        *) return 1 ;;
      esac
    }

    core_pattern_for() {
      case "$1" in
        retroarch-melonds) echo '*melon*ds*_libretro.so' ;;
        retroarch-bsnes-hd) echo '*bsnes*hd*_libretro.so' ;;
        retroarch-mupen64plus) echo '*mupen64plus*_libretro.so' ;;
        retroarch-parallel-n64) echo '*parallel*n64*_libretro.so' ;;
        retroarch-beetle-*) echo '*mednafen*_libretro.so' ;;
        *) echo "*''${1#retroarch-}*_libretro.so" ;;
      esac
    }

    heavy=0
    case "$emulator_id" in
      dolphin|cemu|xemu|ryubing|lime3ds|supermodel|teknoparrot|retroarch-pcsx2|retroarch-beetle-psx-hw|retroarch-beetle-saturn|retroarch-mupen64plus|retroarch-parallel-n64|retroarch-ppsspp|retroarch-flycast) heavy=1 ;;
    esac
    export BOOMER_EMULATOR_HEAVY="$heavy"
    profile_json="$(boomer-display-profile)"
    output_width="$(jq -r '.output_width' <<<"$profile_json")"
    output_height="$(jq -r '.output_height' <<<"$profile_json")"
    render_width="$(jq -r '.render_width' <<<"$profile_json")"
    render_height="$(jq -r '.render_height' <<<"$profile_json")"
    fsr="$(jq -r '.fsr' <<<"$profile_json")"
    fsr_sharpness="$(jq -r '.fsr_sharpness' <<<"$profile_json")"

    cmd=()
    case "$emulator_id" in
      retroarch-*)
        core_file="$(core_file_for "$emulator_id")"
        core_path="${retroarchPackage}/lib/retroarch/cores/$core_file"
        if [ ! -e "$core_path" ]; then
          core_path="$(find "${retroarchPackage}/lib/retroarch/cores" -maxdepth 1 -name "$(core_pattern_for "$emulator_id")" -print -quit || true)"
        fi
        if [ -z "''${core_path:-}" ] || [ ! -e "$core_path" ]; then
          log_event "error" "missing RetroArch core for $emulator_id"
          echo "Missing RetroArch core for $emulator_id" >&2
          exit 66
        fi
        profile="${cfg.configRoot}/retroarch/profiles/current.cfg"
        if [ ! -r "$profile" ]; then
          profile="${cfg.configRoot}/retroarch/profiles/megabezel-auto.cfg"
        fi
        cmd=(retroarch --config "${cfg.configRoot}/retroarch/retroarch.cfg" --appendconfig "$profile" -L "$core_path" "$rom_path")
        ;;
      dolphin)
        cmd=(dolphin-emu -b -e "$rom_path")
        ;;
      cemu)
        cmd=(cemu -f -g "$rom_path")
        ;;
      xemu)
        cmd=(xemu -full-screen -dvd_path "$rom_path")
        ;;
      ryubing)
        cmd=(ryujinx "$rom_path")
        ;;
      lime3ds)
        cmd=(lime3ds "$rom_path")
        ;;
      supermodel)
        cmd=(supermodel "$rom_path" -fullscreen)
        ;;
      gzdoom)
        cmd=(gzdoom -iwad "$rom_path")
        ;;
      pico8)
        cmd=(pico8 -run "$rom_path")
        ;;
      teknoparrot)
        cmd=(boomer-teknoparrot-free "$rom_path")
        ;;
      *)
        log_event "error" "unknown emulator"
        echo "Unknown emulator: $emulator_id" >&2
        exit 64
        ;;
    esac

    log_event "launch" "$profile_json"
    run_cmd=("''${cmd[@]}")
    if [ "''${BOOMER_MANGOHUD:-0}" = "1" ]; then
      run_cmd=(mangohud "''${run_cmd[@]}")
    fi
    if [ "''${BOOMER_DISABLE_GAMESCOPE:-0}" != "1" ]; then
      gamescope_args=(-f -e -W "$output_width" -H "$output_height" -w "$render_width" -h "$render_height")
      if [ "$fsr" = "true" ]; then
        gamescope_args+=(-F fsr --fsr-sharpness "$fsr_sharpness")
      fi
      run_cmd=(gamescope "''${gamescope_args[@]}" -- "''${run_cmd[@]}")
    fi
    if command -v gamemoderun >/dev/null 2>&1; then
      run_cmd=(gamemoderun "''${run_cmd[@]}")
    fi
    exec "''${run_cmd[@]}"
  '';

  boomerTerminalTool = pkgs.writeShellScriptBin "boomer-terminal-tool" ''
    set -euo pipefail
    export PATH=${scriptPath}:${lib.makeBinPath [ pkgs.foot ]}:$PATH
    title="''${1:-Boomer Tool}"
    command="''${2:-true}"
    if [ -n "''${WAYLAND_DISPLAY:-}" ] && command -v foot >/dev/null 2>&1; then
      exec foot -T "$title" sh -lc "$command; status=\$?; printf '\n%s\n' 'Press Enter to close.'; read -r _; exit \$status"
    fi
    exec sh -lc "$command"
  '';

  boomerTeknoparrotFree = pkgs.writeShellScriptBin "boomer-teknoparrot-free" ''
        set -euo pipefail
    export PATH=${scriptPath}:${lib.makeBinPath [ winePackage pkgs.curl pkgs.unzip ]}:$PATH
        prefix="${cfg.configRoot}/teknoparrot"
        install_dir="$prefix/TeknoParrot"
        rom="''${1:-}"
        mkdir -p "$prefix" "${cfg.dataRoot}/logs/teknoparrot"
        export WINEPREFIX="$prefix/prefix"
        export WINEARCH=win64
        if [ ! -e "$install_dir/TeknoParrotUi.exe" ]; then
          cat >&2 <<'EOF'
    TeknoParrot free is scaffolded but not installed yet.

    Place the official free TeknoParrot files under:
      ${cfg.configRoot}/teknoparrot/TeknoParrot

    No premium unlocks, bypasses, commercial game files, or third-party patch packs
    are managed by this module.
    EOF
          exit 69
        fi
        exec wine "$install_dir/TeknoParrotUi.exe" "$rom"
  '';

  boomerRenderScraperSettings = pkgs.writeShellScriptBin "boomer-render-esde-scraper-settings" ''
        set -euo pipefail
        export PATH=${scriptPath}:${lib.makeBinPath [ pkgs.python3 ]}:$PATH
        secret_env="/run/ghostship-secrets/emulation-scraper.env"
        settings="${cfg.esde.appDataDir}/settings/es_settings.xml"
        [ -r "$secret_env" ] || exit 0
        python3 - "$secret_env" "$settings" <<'PY'
    import os
    import shlex
    import sys
    import tempfile
    import xml.etree.ElementTree as ET
    from pathlib import Path

    env_path = Path(sys.argv[1])
    settings_path = Path(sys.argv[2])

    values = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            value = shlex.split(value)[0] if value else ""
        except ValueError:
            pass
        values[key] = value

    if settings_path.exists():
        tree = ET.parse(settings_path)
        root = tree.getroot()
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("settings")
        tree = ET.ElementTree(root)

    def set_entry(tag, name, value):
        for entry in root.findall(tag):
            if entry.get("name") == name:
                entry.set("value", value)
                return
        ET.SubElement(root, tag, {"name": name, "value": value})

    if values.get("SCREENSCRAPER_USER"):
        set_entry("string", "ScraperUsernameScreenScraper", values["SCREENSCRAPER_USER"])
    if values.get("SCREENSCRAPER_PASS"):
        set_entry("string", "ScraperPasswordScreenScraper", values["SCREENSCRAPER_PASS"])
    if values.get("SCREENSCRAPER_USER") and values.get("SCREENSCRAPER_PASS"):
        set_entry("bool", "ScraperUseAccountScreenScraper", "true")
    set_entry("string", "Scraper", "screenscraper")
    set_entry("bool", "ScrapeVideos", "true")
    set_entry("bool", "ScrapeScreenshots", "true")
    set_entry("bool", "ScrapeCovers", "true")
    set_entry("bool", "ScrapeMarquees", "true")
    set_entry("bool", "MiximageGenerate", "true")

    fd, tmp = tempfile.mkstemp(prefix="es_settings.", dir=str(settings_path.parent))
    os.close(fd)
    tree.write(tmp, encoding="utf-8", xml_declaration=True)
    os.chmod(tmp, 0o640)
    Path(tmp).replace(settings_path)
    PY
        chown ${cfg.user}:${cfg.group} "$settings"
        chmod 0640 "$settings"
  '';

  boomerSyncEsdeConfig = pkgs.writeShellScriptBin "boomer-sync-esde-config" ''
    set -euo pipefail
    export PATH=${scriptPath}:${lib.makeBinPath [ pkgs.jq boomerRenderScraperSettings ]}:$PATH

    install -d -m 0755 -o ${cfg.user} -g ${cfg.group} \
      "${cfg.dataRoot}" \
      "${cfg.romRoot}" \
      "${cfg.biosRoot}" \
      "${cfg.dataRoot}/saves" \
      "${cfg.dataRoot}/states" \
      "${cfg.dataRoot}/screenshots" \
      "${cfg.configRoot}" \
      "${cfg.configRoot}/retroarch" \
      "${cfg.configRoot}/retroarch/profiles" \
      "${cfg.configRoot}/retroarch/remaps" \
      "${cfg.configRoot}/retroarch/shaders" \
      "${cfg.configRoot}/retroarch/shaders-user" \
      "${cfg.configRoot}/es-de" \
      "${cfg.dataRoot}/logs" \
      "${cfg.dataRoot}/logs/retroarch" \
      "${cfg.dataRoot}/tools" \
      "${cfg.esde.appDataDir}" \
      "${cfg.esde.appDataDir}/custom_systems" \
      "${cfg.esde.appDataDir}/settings" \
      "${cfg.esde.appDataDir}/themes" \
      "${cfg.esde.appDataDir}/scripts"

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esSystemsXml} "${cfg.esde.appDataDir}/custom_systems/es_systems.xml"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${esFindRulesXml} "${cfg.esde.appDataDir}/custom_systems/es_find_rules.xml"
    if [ ! -e "${cfg.esde.appDataDir}/settings/es_settings.xml" ]; then
      install -D -m 0640 -o ${cfg.user} -g ${cfg.group} ${esSettingsXml} "${cfg.esde.appDataDir}/settings/es_settings.xml"
    fi

    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchCfg} "${cfg.configRoot}/retroarch/retroarch.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchCoreOptions} "${cfg.configRoot}/retroarch/core-options.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchMegabezelProfile} "${cfg.configRoot}/retroarch/profiles/megabezel-auto.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchMegabezelProfile} "${cfg.configRoot}/retroarch/profiles/megabezel-standard.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchPotatoProfile} "${cfg.configRoot}/retroarch/profiles/megabezel-potato.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchPassthroughProfile} "${cfg.configRoot}/retroarch/profiles/megabezel-passthrough.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchSharpProfile} "${cfg.configRoot}/retroarch/profiles/sharp-clean.cfg"
    install -D -m 0644 -o ${cfg.user} -g ${cfg.group} ${retroarchIntegerProfile} "${cfg.configRoot}/retroarch/profiles/integer-raw.cfg"
    if [ ! -e "${cfg.configRoot}/retroarch/profiles/current.cfg" ]; then
      ln -s "megabezel-auto.cfg" "${cfg.configRoot}/retroarch/profiles/current.cfg"
    fi

    ln -sfn ${artBookNext}/share/es-de/themes/art-book-next-es-de "${cfg.esde.appDataDir}/themes/art-book-next-es-de"
    ln -sfn ${shaderSlang}/share/libretro/shaders_slang "${cfg.configRoot}/retroarch/shaders/shaders_slang"
    ln -sfn ${shaderGlsl}/share/libretro/shaders_glsl "${cfg.configRoot}/retroarch/shaders/shaders_glsl"
    ln -sfn ${shaderCg}/share/libretro/shaders_cg "${cfg.configRoot}/retroarch/shaders/shaders_cg"

    printf '%s' '${allSystemsJson}' | jq -c '.[]' | while read -r system; do
      folder="$(jq -r '.folder' <<<"$system")"
      source="/mnt/z/Library/ROMs/roms/$folder"
      target="${cfg.romRoot}/$folder"
      if [ -e "$source" ] && [ ! -e "$target" ]; then
        ln -s "$source" "$target"
      elif [ ! -e "$target" ]; then
        install -d -m 0755 -o ${cfg.user} -g ${cfg.group} "$target"
      fi
    done

    ${lib.concatMapStringsSep "\n" (tool: ''
      ln -sfn ${lib.getExe (builtins.getAttr tool.target toolScripts)} "${cfg.dataRoot}/tools/${tool.file}"
    '') tools}

    ln -sfn "${cfg.dataRoot}" /home/${cfg.user}/Emulation
    chown -h ${cfg.user}:${cfg.group} /home/${cfg.user}/Emulation || true
    boomer-render-esde-scraper-settings || true
  '';

  boomerEmulationSession = pkgs.writeShellScriptBin "boomer-emulation-session" ''
    set -euo pipefail
    export PATH=${scriptPath}:${lib.makeBinPath [ boomerSyncEsdeConfig esdePackage pkgs.gamescope ]}:$PATH
    export ESDE_APPDATA_DIR="${cfg.esde.appDataDir}"
    export XDG_DATA_HOME="${cfg.dataRoot}/xdg/share"
    export XDG_CONFIG_HOME="${cfg.dataRoot}/xdg/config"
    export XDG_CACHE_HOME="${cfg.dataRoot}/xdg/cache"
    export SDL_GAMECONTROLLERCONFIG_FILE="${cfg.configRoot}/controllers/gamecontrollerdb.txt"
    boomer-sync-esde-config
    if [ "''${BOOMER_ESDE_NO_GAMESCOPE:-0}" = "1" ]; then
      exec es-de --fullscreen
    fi
    exec gamescope -f -e -- es-de --fullscreen
  '';

  boomerControllerLeds = pkgs.writeShellScriptBin "boomer-controller-leds" ''
    set -euo pipefail
    export PATH=${scriptPath}:$PATH
    state_dir="${cfg.configRoot}/controllers"
    order_file="$state_dir/player-order.json"
    log_file="${cfg.dataRoot}/logs/controller-leds.log"
    mkdir -p "$state_dir" "$(dirname "$log_file")"
    touch "$log_file"
    chown ${cfg.user}:${cfg.group} "$state_dir" "$log_file" || true

    while true; do
      mapfile -t devices < <(bluetoothctl devices Connected 2>/dev/null | awk '{print $2}' || true)
      if [ ! -s "$order_file" ]; then
        printf '%s\n' "''${devices[@]}" | jq -R -s 'split("\n") | map(select(length > 0)) | {players: .}' >"$order_file"
        chown ${cfg.user}:${cfg.group} "$order_file" || true
      fi
      player=1
      for led in /sys/class/leds/*; do
        [ -e "$led/brightness" ] || continue
        name="$(basename "$led")"
        case "$name" in
          *player*|*pro_controller*|*8BitDo*|*nintendo*)
            if [ "$player" -le 4 ]; then
              echo 1 >"$led/brightness" 2>/dev/null || true
              echo "$(date -u +%FT%TZ) set $name for player $player" >>"$log_file"
              player=$((player + 1))
            fi
            ;;
        esac
      done
      sleep 2
    done
  '';

  boomerRetroarchShaderSmokeTest = pkgs.writeShellScriptBin "boomer-retroarch-shader-smoke-test" ''
    set -euo pipefail
    shader_root="${cfg.configRoot}/retroarch/shaders"
    missing=0
    for path in \
      "$shader_root/shaders_slang" \
      "$shader_root/shaders_slang/bezel/Mega_Bezel" \
      "$shader_root/shaders_glsl" \
      "$shader_root/shaders_cg"; do
      if [ -e "$path" ]; then
        printf 'ok %s\n' "$path"
      else
        printf 'missing %s\n' "$path" >&2
        missing=1
      fi
    done
    ${retroarchPackage}/bin/retroarch --version | head -n 1
    exit "$missing"
  '';

  mkTool = name: command:
    pkgs.writeShellScriptBin name ''
      set -euo pipefail
      export PATH=${scriptPath}:${lib.makeBinPath [
        boomerTerminalTool
        boomerDisplayProfile
        boomerRetroarchShaderSmokeTest
        boomerRenderScraperSettings
        retroarchPackage
        pkgs.jq
      ]}:$PATH
      exec boomer-terminal-tool "${name}" ${lib.escapeShellArg command}
    '';

  profileToolCommand = ''
    profile_dir="${cfg.configRoot}/retroarch/profiles"
    current="$profile_dir/current.cfg"
    echo "Current profile:"
    readlink "$current" 2>/dev/null || echo "custom or missing"
    echo
    echo "Available profiles:"
    find "$profile_dir" -maxdepth 1 -type f -name "*.cfg" -printf "%f\n" | sort
    echo
    echo "To change profile:"
    echo "  ln -sfn <profile>.cfg $current"
  '';

  toolScripts = {
    boomer-wifi-status = mkTool "boomer-wifi-status" "nmcli radio; echo; nmcli device status || true";
    boomer-wifi-connect = mkTool "boomer-wifi-connect" "nmcli radio wifi on || true; nmtui";
    boomer-bluetooth-status = mkTool "boomer-bluetooth-status" "bluetoothctl show; echo; bluetoothctl devices Paired; echo; bluetoothctl devices Connected";
    boomer-bluetooth-pair-controller = mkTool "boomer-bluetooth-pair-controller" "bluetoothctl power on; bluetoothctl agent on; bluetoothctl default-agent; echo 'Put the controller in pairing mode, then use scan/pair/trust/connect.'; bluetoothctl";
    boomer-bluetooth-reconnect-controllers = mkTool "boomer-bluetooth-reconnect-controllers" "bluetoothctl devices Paired | awk '{print $2}' | while read -r mac; do bluetoothctl trust \"$mac\" || true; bluetoothctl connect \"$mac\" || true; done; bluetoothctl devices Connected";
    boomer-player-assignment = mkTool "boomer-player-assignment" "mkdir -p ${cfg.configRoot}/controllers; bluetoothctl devices Connected | awk '{print $2}' | jq -R -s 'split(\"\\n\") | map(select(length > 0)) | {players: .}' > ${cfg.configRoot}/controllers/player-order.json; cat ${cfg.configRoot}/controllers/player-order.json";
    boomer-display-profile-tool = mkTool "boomer-display-profile-tool" "boomer-display-profile | jq .";
    boomer-display-profile-override = mkTool "boomer-display-profile-override" "echo 'Set BOOMER_DISPLAY_WIDTH, BOOMER_DISPLAY_HEIGHT, BOOMER_RENDER_SIZE, BOOMER_FORCE_FSR, or BOOMER_DISABLE_FSR in ${cfg.configRoot}/display.env, then restart ES-DE.'; [ -r ${cfg.configRoot}/display.env ] && cat ${cfg.configRoot}/display.env || true";
    boomer-retroarch-core-status = mkTool "boomer-retroarch-core-status" "echo 'RetroArch:'; retroarch --version | head -n 1; echo; echo 'Cores:'; find ${retroarchPackage}/lib/retroarch/cores -maxdepth 1 -name '*_libretro.so' -printf '%f\\n' | sort; echo; boomer-retroarch-shader-smoke-test";
    boomer-retroarch-graphics-profiles = mkTool "boomer-retroarch-graphics-profiles" profileToolCommand;
    boomer-retroarch-shader-profiles = mkTool "boomer-retroarch-shader-profiles" profileToolCommand;
    boomer-esde-scraper-status = mkTool "boomer-esde-scraper-status" "boomer-render-esde-scraper-settings || true; echo 'Projection:'; ls -l /run/ghostship-secrets/emulation-scraper.env 2>/dev/null || true; echo; grep -E 'Scraper|Miximage' ${cfg.esde.appDataDir}/settings/es_settings.xml || true";
    boomer-esde-scrape-missing-media = mkTool "boomer-esde-scrape-missing-media" "boomer-render-esde-scraper-settings || true; echo 'Open ES-DE > Main Menu > Scraper. Credentials and rich media defaults have been projected when secrets are available.'";
    boomer-restart-esde = pkgs.writeShellScriptBin "boomer-restart-esde" ''
      set -euo pipefail
      systemctl --user restart graphical-session.target 2>/dev/null || loginctl terminate-user ${cfg.user}
    '';
    boomer-shutdown = pkgs.writeShellScriptBin "boomer-shutdown" ''
      set -euo pipefail
      systemctl poweroff
    '';
    boomer-reboot = pkgs.writeShellScriptBin "boomer-reboot" ''
      set -euo pipefail
      systemctl reboot
    '';
  };

in
{
  options.ghostship.emulation = {
    enable = mkEnableOption "dedicated ES-DE emulation PC profile";
    user = mkOption {
      type = types.str;
      default = "kiosk";
      description = "User that runs the emulation kiosk session.";
    };
    group = mkOption {
      type = types.str;
      default = "kiosk";
      description = "Primary group for emulation runtime state.";
    };
    dataRoot = mkOption {
      type = types.path;
      default = "/srv/emulation";
      description = "Writable root for emulation state.";
    };
    romRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/roms";
      description = "Local ROM root. The future 4TB SSD should mount here.";
    };
    biosRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/bios";
      description = "BIOS, firmware, keys, and other user-provided emulator files.";
    };
    configRoot = mkOption {
      type = types.path;
      default = "/srv/emulation/config";
      description = "Writable configuration root for emulator overrides.";
    };
    frontend = mkOption {
      type = types.enum [ "es-de" ];
      default = "es-de";
      description = "Frontend to launch from the kiosk session.";
    };
    theme = mkOption {
      type = types.enum [ "art-book-next" ];
      default = "art-book-next";
      description = "Default ES-DE theme.";
    };
    esde.appDataDir = mkOption {
      type = types.path;
      default = "/srv/emulation/es-de";
      description = "ES-DE application data directory.";
    };
    visuals.defaultProfile = mkOption {
      type = types.enum [ "megabezel-auto" "megabezel-standard" "megabezel-potato" "megabezel-passthrough" "sharp-clean" "integer-raw" "performance" ];
      default = "megabezel-auto";
      description = "Default RetroArch shader/profile policy.";
    };
    visuals.upscaler = mkOption {
      type = types.enum [ "gamescope-fsr-auto" ];
      default = "gamescope-fsr-auto";
      description = "Cross-emulator upscaling policy.";
    };
    controllers.assignment = mkOption {
      type = types.enum [ "connection-order-persistent" ];
      default = "connection-order-persistent";
      description = "Player assignment policy for Bluetooth controllers.";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.frontend == "es-de";
        message = "boomer-kuwanger emulation profile only supports ES-DE.";
      }
    ];

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

    age.identityPaths = lib.mkDefault [ "/etc/ssh/ssh_host_ed25519_key" ];
    age.secrets.emulation-scraper-secrets = {
      file = ../../secrets/files/services/emulation-scraper-secrets.env.age;
      mode = "0400";
    };

    boot.kernelParams = [ "amd_pstate=active" ];
    boot.kernelModules = [ "amdgpu" "hid-nintendo" ];
    boot.extraModprobeConfig = ''
      options btusb enable_autosuspend=n
    '';

    hardware.graphics = {
      enable = true;
      enable32Bit = true;
    };

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
      settings = {
        General = {
          Experimental = true;
          FastConnectable = true;
          ControllerMode = "dual";
          JustWorksRepairing = "always";
          Privacy = "off";
        };
        Policy = {
          AutoEnable = true;
        };
      };
    };

    networking.networkmanager.enable = lib.mkDefault true;
    programs.gamemode.enable = true;
    services.libinput.enable = true;

    services.greetd = {
      enable = true;
      settings.default_session = {
        command = "${lib.getExe boomerEmulationSession}";
        user = cfg.user;
      };
    };

    services.udev.extraRules = ''
      # 8BitDo Ultimate 2C Bluetooth and Nintendo Switch Pro mode controller identities.
      SUBSYSTEM=="usb", ATTR{idVendor}=="2dc8", ATTR{idProduct}=="310b", TEST=="power/control", ATTR{power/control}="on"
      SUBSYSTEM=="usb", ATTR{idVendor}=="057e", ATTR{idProduct}=="2009", TEST=="power/control", ATTR{power/control}="on"
      KERNEL=="hidraw*", ATTRS{idVendor}=="2dc8", ATTRS{idProduct}=="310b", MODE="0660", GROUP="input", TAG+="uaccess"
      KERNEL=="hidraw*", ATTRS{idVendor}=="057e", ATTRS{idProduct}=="2009", MODE="0660", GROUP="input", TAG+="uaccess"
    '';

    environment.sessionVariables = {
      ESDE_APPDATA_DIR = cfg.esde.appDataDir;
      BOOMER_EMULATION_DATA_ROOT = cfg.dataRoot;
      BOOMER_EMULATION_CONFIG_ROOT = cfg.configRoot;
      MESA_SHADER_CACHE_DIR = "${cfg.dataRoot}/cache/mesa-shaders";
      RADV_PERFTEST = "gpl";
    };

    environment.systemPackages = [
      artBookNext
      boomerDisplayProfile
      boomerEmulationSession
      boomerRenderScraperSettings
      boomerRetroarchShaderSmokeTest
      boomerRunEmulator
      boomerSyncEsdeConfig
      boomerTeknoparrotFree
      boomerTerminalTool
      esdePackage
      joypadAutoconfig
      pico8Package
      retroarchPackage
      shaderCg
      shaderGlsl
      shaderSlang
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
      winePackage
    ]
    ++ builtins.attrValues toolScripts
    ++ optionalPackages [
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
    ++ lib.optional (supermodelPackage != null) supermodelPackage;

    systemd.tmpfiles.rules = [
      "d ${cfg.dataRoot} 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.romRoot} 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.biosRoot} 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataRoot}/saves 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataRoot}/states 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataRoot}/screenshots 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.configRoot} 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.configRoot}/retroarch 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.configRoot}/retroarch/shaders 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.configRoot}/retroarch/shaders-user 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.configRoot}/es-de 0755 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataRoot}/logs 0755 ${cfg.user} ${cfg.group} -"
      "d /run/ghostship-secrets 0755 root root -"
      "L+ /home/${cfg.user}/Emulation - - - - ${cfg.dataRoot}"
    ];

    systemd.services.boomer-emulation-setup = {
      description = "Prepare Boomer Kuwanger emulation runtime state";
      wantedBy = [ "multi-user.target" ];
      before = [ "greetd.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ boomerSyncEsdeConfig ];
      script = ''
        boomer-sync-esde-config
      '';
    };

    systemd.services.boomer-emulation-secrets = {
      description = "Project Boomer Kuwanger emulation scraper secrets";
      wantedBy = [ "multi-user.target" ];
      after = [ "agenix.service" "boomer-emulation-setup.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ pkgs.coreutils pkgs.gawk boomerRenderScraperSettings ];
      script = ''
        secret_path="${config.age.secrets.emulation-scraper-secrets.path}"
        projection="/run/ghostship-secrets/emulation-scraper.env"
        if [ -r "$secret_path" ]; then
          install -d -m 0755 /run/ghostship-secrets
          awk -F= '
            /^[[:space:]]*($|#)/ { next }
            $1 ~ /^(SCREENSCRAPER_USER|SCREENSCRAPER_PASS|THEGAMESDB_API_KEY)$/ { print }
          ' "$secret_path" >"$projection.tmp"
          chown ${cfg.user}:${cfg.group} "$projection.tmp"
          chmod 0440 "$projection.tmp"
          mv "$projection.tmp" "$projection"
          boomer-render-esde-scraper-settings || true
        fi
      '';
    };

    systemd.services.boomer-disable-wifi = {
      description = "Disable Wi-Fi radio for Bluetooth-focused emulation profile";
      wantedBy = [ "multi-user.target" ];
      after = [ "NetworkManager.service" "bluetooth.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ pkgs.networkmanager pkgs.util-linux ];
      script = ''
        nmcli radio wifi off || true
        rfkill block wlan || true
      '';
    };

    systemd.services.boomer-controller-leds = {
      description = "Maintain Boomer Kuwanger controller player LED state";
      wantedBy = [ "multi-user.target" ];
      after = [ "bluetooth.service" "boomer-emulation-setup.service" ];
      serviceConfig = {
        ExecStart = "${lib.getExe boomerControllerLeds}";
        Restart = "always";
        RestartSec = "2s";
      };
    };

    systemd.services.joycond = lib.mkIf (pkgs ? joycond) {
      description = "Joy-Con and Switch Pro controller userspace daemon";
      wantedBy = [ "multi-user.target" ];
      after = [ "bluetooth.service" ];
      serviceConfig = {
        ExecStart = "${pkgs.joycond}/bin/joycond";
        Restart = "on-failure";
      };
    };

    systemd.services.joycond-cemuhook = lib.mkIf (pkgs ? joycond-cemuhook) {
      description = "Joycond Cemuhook motion server";
      wantedBy = [ "multi-user.target" ];
      after = [ "joycond.service" ];
      serviceConfig = {
        ExecStart = "${pkgs.joycond-cemuhook}/bin/joycond-cemuhook";
        Restart = "on-failure";
      };
    };
  };
}
