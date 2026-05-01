{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

  winePackage =
    if pkgs ? wineWowPackages && pkgs.wineWowPackages ? staging then
      pkgs.wineWowPackages.staging
    else if pkgs ? wineWow64Packages && pkgs.wineWow64Packages ? staging then
      pkgs.wineWow64Packages.staging
    else
      pkgs.wine;

  supermodelPackage =
    if pkgs ? supermodel then
      pkgs.supermodel.overrideAttrs (old: {
        postPatch = (old.postPatch or "") + ''
          if [ -f Src/Game.h ] && ! grep -q '<cstdint>' Src/Game.h; then
            sed -i '1i #include <cstdint>' Src/Game.h
          fi
        '';
      })
    else
      null;

  gzdoomPackage =
    if pkgs ? gzdoom then
      pkgs.gzdoom.overrideAttrs (old: {
        postPatch = (old.postPatch or "") + ''
          substituteInPlace src/common/menu/menu.cpp \
            --replace-fail "case KEY_JOY1:" "case GHOSTSHIP_KEY_JOY1:" \
            --replace-fail "case KEY_JOY2:" "case KEY_JOY1:" \
            --replace-fail "case GHOSTSHIP_KEY_JOY1:" "case KEY_JOY2:"
        '';
      })
    else
      null;

  retroarchPackage = pkgs.retroarch.withCores (
    cores: lib.filter (core: core != null) (map (name: cores.${name} or null) emu.coreNames)
  );

  emptyJoypadAutoconfig = pkgs.runCommand "empty-retroarch-joypad-autoconfig" { } ''
    mkdir -p $out/share/libretro/autoconfig
  '';

  ryubingCanaryPin = import ./ryubing-canary-pin.nix;

  ryubingCanaryRuntimeLibs = [
    pkgs.alsa-lib
    pkgs.fontconfig
    pkgs.freetype
    pkgs.glib
    pkgs.gtk3
    pkgs.icu
    pkgs.jack2
    pkgs.libGL
    pkgs.libdrm
    pkgs.libdecor
    pkgs.libice
    pkgs.libpulseaudio
    pkgs.libsm
    pkgs.libusb1
    pkgs.libxscrnsaver
    pkgs.libxtst
    pkgs.libxkbcommon
    pkgs.openssl
    pkgs.pipewire
    pkgs.sndio
    pkgs.stdenv.cc.cc.lib
    pkgs.udev
    pkgs.vulkan-loader
    pkgs.wayland
    pkgs.libx11
    pkgs.libxcursor
    pkgs.libxext
    pkgs.libxi
    pkgs.libxrandr
    pkgs.libxcb
  ];

  ryubingCanaryPackage = pkgs.stdenv.mkDerivation {
    pname = "ryubing-canary";
    inherit (ryubingCanaryPin) version;

    src = pkgs.fetchurl {
      inherit (ryubingCanaryPin) url hash;
    };

    nativeBuildInputs = [
      pkgs.autoPatchelfHook
      pkgs.makeWrapper
    ];

    buildInputs = ryubingCanaryRuntimeLibs;
    autoPatchelfIgnoreMissingDeps = [
      "libGLES_CM.so.1"
      "libsteam_api.so"
    ];

    sourceRoot = ".";
    dontBuild = true;

    installPhase = ''
      runHook preInstall
      mkdir -p "$out/opt/ryubing-canary" "$out/bin"
      cp -R publish/. "$out/opt/ryubing-canary/"
      chmod +x "$out/opt/ryubing-canary/Ryujinx" "$out/opt/ryubing-canary/Ryujinx.sh" || true
      makeWrapper "$out/opt/ryubing-canary/Ryujinx" "$out/bin/ryujinx" \
        --set LANG C.UTF-8 \
        --set DOTNET_EnableAlternateStackCheck 1 \
        --prefix LD_LIBRARY_PATH : "$out/opt/ryubing-canary:${lib.makeLibraryPath ryubingCanaryRuntimeLibs}"
      ln -s "$out/bin/ryujinx" "$out/bin/Ryujinx"
      runHook postInstall
    '';

    meta = {
      homepage = "https://git.ryujinx.app/Ryubing/Canary/releases";
      description = "Ryubing Canary Nintendo Switch emulator binary release";
      license = lib.licenses.mit;
      platforms = [ "x86_64-linux" ];
      mainProgram = "ryujinx";
    };
  };

  joypadAutoconfig =
    if pkgs ? retroarch-joypad-autoconfig then
      pkgs.retroarch-joypad-autoconfig
    else
      emptyJoypadAutoconfig;

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
      theme_dir="$out/share/es-de/themes/art-book-next-es-de"
      mkdir -p "$theme_dir"
      cp -R . "$theme_dir/"
      find "$theme_dir" -maxdepth 1 -name 'aspect-ratio*.xml' -exec \
        sed -i '/<clock name="clock">/a\         <format>%H:%M</format>' {} +
      runHook postInstall
    '';
  };

  shaderSlang = pkgs.stdenvNoCC.mkDerivation {
    pname = "emulation-libretro-shaders-slang";
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
    pname = "emulation-libretro-shaders-glsl";
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
    pname = "emulation-libretro-shaders-cg";
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
    nativeBuildInputs = [
      pkgs.makeWrapper
      pkgs.unzip
    ];
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
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.packages = {
      inherit
        artBookNext
        emptyJoypadAutoconfig
        esdePackage
        gzdoomPackage
        joypadAutoconfig
        pico8Package
        retroarchPackage
        ryubingCanaryPackage
        shaderCg
        shaderGlsl
        shaderSlang
        supermodelPackage
        winePackage
        ;
    };
  };
}
