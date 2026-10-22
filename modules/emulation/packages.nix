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

  wineMono = pkgs.stdenvNoCC.mkDerivation {
    pname = "wine-mono";
    version = "10.4.1";

    src = pkgs.fetchurl {
      url = "https://dl.winehq.org/wine/wine-mono/10.4.1/wine-mono-10.4.1-x86.msi";
      hash = "sha256-Bx9LKIfhyXoR15H/PWW+lCnu1t7EwnCIiL/VRro1jiM=";
    };

    dontUnpack = true;

    installPhase = ''
      runHook preInstall
      install -D -m 0644 "$src" "$out/share/wine/mono/wine-mono-10.4.1-x86.msi"
      runHook postInstall
    '';
  };

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

  libretroCoreInfo = pkgs.libretro-core-info;

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
    teknoparrotArtwork = ./assets/teknoparrot-afterburner.png;
    teknoparrotLogo = ./assets/teknoparrot.svg;
    installPhase = ''
      runHook preInstall
      theme_dir="$out/share/es-de/themes/art-book-next-es-de"
      mkdir -p "$theme_dir"
      cp -R . "$theme_dir/"
      find "$theme_dir" -maxdepth 1 -name 'aspect-ratio*.xml' -exec \
        sed -i '/<clock name="clock">/a\         <format>%H:%M</format>' {} +
      ${pkgs.python3}/bin/python3 - "$theme_dir" teknoparrot "$teknoparrotArtwork" <<'PY'
import struct
import sys
import zlib
from pathlib import Path

theme_dir = Path(sys.argv[1])
artwork_args = sys.argv[2:]


def read_png(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"not a PNG: {path}")
    offset = 8
    width = height = None
    color_type = None
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk)
            if bit_depth != 8 or color_type not in (2, 6):
                raise SystemExit(f"unsupported PNG format: {path}")
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            break
    raw = zlib.decompress(bytes(compressed))
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    rows = []
    previous = [0] * stride
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        row = list(raw[pos:pos + stride])
        pos += stride
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                row[i] = (value + left) & 255
            elif filter_type == 2:
                row[i] = (value + up) & 255
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 255
            elif filter_type == 4:
                p = left + up - up_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - up_left)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else up_left
                row[i] = (value + predictor) & 255
            elif filter_type != 0:
                raise SystemExit(f"unsupported PNG filter {filter_type}: {path}")
        rows.append(row)
        previous = row
    return width, height, channels, rows


def write_rgba_png(path, width, height, pixels):
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        start = y * stride
        raw.extend(pixels[start:start + stride])
    chunks = []
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    for chunk_type, chunk in (
        (b"IHDR", ihdr),
        (b"IDAT", zlib.compress(bytes(raw), 9)),
        (b"IEND", b""),
    ):
        chunks.append(struct.pack(">I", len(chunk)))
        chunks.append(chunk_type)
        chunks.append(chunk)
        chunks.append(struct.pack(">I", zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"".join(chunks))


for system_id, source_arg in zip(artwork_args[0::2], artwork_args[1::2]):
    source = Path(source_arg)
    width, height, channels, rows = read_png(source)
    if (width, height) != (454, 1080):
        raise SystemExit(f"{system_id} artwork must be 454x1080, got {width}x{height}")

    pixels = bytearray(width * height * 4)
    for y, row in enumerate(rows):
        for x in range(width):
            src = x * channels
            dst = (y * width + x) * 4
            pixels[dst:dst + 3] = bytes(row[src:src + 3])
            # Match Art Book Next's diagonal system-art mask:
            # polygon points are (112.4,0), (452.25,0), (339.8,1080), (0,1080).
            left = 112.424625 * (1 - y / 1079)
            right = 452.25 - 112.424625 * (y / 1079)
            pixels[dst + 3] = 255 if left <= x <= right else 0

    for rel in [
        f"_inc/systems/artwork/{system_id}.png",
        f"_inc/systems/artwork-screenshots/{system_id}.png",
        f"_inc/systems/artwork-outline/{system_id}.png",
    ]:
        write_rgba_png(theme_dir / rel, width, height, pixels)
PY
      install -m 0644 "$teknoparrotLogo" "$theme_dir/_inc/systems/logos/teknoparrot.svg"
      cat >"$theme_dir/_inc/systems/_metadata-global/teknoparrot.xml" <<'EOF'
<theme>
    <variables>
        <systemName>TeknoParrot</systemName>
        <systemDescription>TeknoParrot arcade launchers for PC-based arcade games.</systemDescription>
        <systemManufacturer>Various</systemManufacturer>
        <systemReleaseYear>Various</systemReleaseYear>
        <systemReleaseDate>Various</systemReleaseDate>
        <systemReleaseDateFormated>Various</systemReleaseDateFormated>
        <systemHardwareType>Arcade</systemHardwareType>
        <systemCoverSize>3-4</systemCoverSize>
        <systemCoverSizeType>portrait</systemCoverSizeType>
        <systemColor>5B60B7</systemColor>
        <systemColorPalette1>F15A24</systemColorPalette1>
        <systemColorPalette2>F6DD08</systemColorPalette2>
        <systemColorPalette3>303030</systemColorPalette3>
        <systemColorPalette4>FFFFFF</systemColorPalette4>
        <systemCartSize>1-1</systemCartSize>
    </variables>
</theme>
EOF
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
      url = "file:///mnt/c/Users/$(cat /etc/ghostship/windows-user 2>/dev/null || echo default)/Downloads/pico-8_0.2.7_amd64.zip";
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
        libretroCoreInfo
        pico8Package
        retroarchPackage
        ryubingCanaryPackage
        shaderCg
        shaderGlsl
        shaderSlang
        supermodelPackage
        wineMono
        winePackage
        ;
    };
  };
}
