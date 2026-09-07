{
  lib,
  stdenv,
  buildNpmPackage,
  fetchurl,
  autoPatchelfHook,
  dpkg,
  imagemagick,
  nodejs_24,
  alsa-lib,
  at-spi2-atk,
  cairo,
  cups,
  dbus,
  expat,
  gdk-pixbuf,
  glib,
  gtk3,
  gtk4,
  nss,
  nspr,
  libx11,
  libxcb,
  libxcomposite,
  libxdamage,
  libxext,
  libxfixes,
  libxrandr,
  libxkbfile,
  pango,
  pciutils,
  systemd,
  libnotify,
  pipewire,
  libsecret,
  libpulseaudio,
  speechd-minimal,
  libdrm,
  libgbm,
  libxkbcommon,
  libxshmfence,
  libGL,
  vulkan-loader,
  libusb1,
  zlib,
}:
let
  release = builtins.fromJSON (builtins.readFile ./releases/26.901.51231.json);
  upstreamArchive = fetchurl {
    inherit (release) url;
    sha256 = release.sha256;
  };
in
buildNpmPackage {
  pname = "ghostship-codex-desktop-web";
  version = release.desktopVersion;
  src = lib.cleanSourceWith {
    src = ./.;
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        ".cache"
        "dist"
        "node_modules"
      ]);
  };
  npmDepsHash = "sha256-yTubtHOrfBUH301tZxSzwFdKLENQk5iGUfjwS5VdfWI=";
  npmInstallFlags = [ "--ignore-scripts" ];
  dontNpmBuild = true;
  nativeBuildInputs = [
    autoPatchelfHook
    dpkg
    imagemagick
    nodejs_24
  ];
  buildInputs = [
    alsa-lib
    at-spi2-atk
    cairo
    cups
    dbus
    expat
    gdk-pixbuf
    glib
    gtk3
    gtk4
    nss
    nspr
    libx11
    libxcb
    libxcomposite
    libxdamage
    libxext
    libxfixes
    libxrandr
    libxkbfile
    pango
    pciutils
    stdenv.cc.cc.lib
    systemd
    libnotify
    pipewire
    libsecret
    libpulseaudio
    speechd-minimal
    libdrm
    libgbm
    libxkbcommon
    libxshmfence
    libGL
    vulkan-loader
    libusb1
    zlib
  ];
  # Electron loads these libraries dynamically; retain them in the runtime path.
  runtimeDependencies = [
    libGL
    libgbm
    libsecret
    libpulseaudio
    vulkan-loader
  ];
  buildPhase = ''
    runHook preBuild
    node scripts/prepare-linux.mjs --release ${release.desktopVersion} \
      --archive ${upstreamArchive} --output "$PWD/prepared"
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    cp -a prepared "$out"
    runHook postInstall
  '';
  # Preserve native code and resource data; only ELF loader/library paths change.
  dontStrip = true;
  meta = {
    description = "Web-native transport for the official ChatGPT Linux desktop app";
    homepage = "https://learn.chatgpt.com/docs/linux/linux-app";
    license = lib.licenses.unfree;
    platforms = [ "aarch64-linux" ];
  };
}
