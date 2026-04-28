{ config, lib, pkgs, ... }:

let
  cfg = config.ghostship.emulation;
  emu = config.ghostship.emulation.internal.lib;

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

  retroarchPackage = pkgs.retroarch.withCores (cores:
    lib.filter (core: core != null) (map (name: cores.${name} or null) emu.coreNames));

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
in
{
  config = lib.mkIf cfg.enable {
    ghostship.emulation.internal.packages = {
      inherit
        artBookNext
        emptyJoypadAutoconfig
        esdePackage
        joypadAutoconfig
        pico8Package
        retroarchPackage
        shaderCg
        shaderGlsl
        shaderSlang
        supermodelPackage
        winePackage
        ;
    };
  };
}
