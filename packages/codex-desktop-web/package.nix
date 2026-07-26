{
  lib,
  stdenv,
  buildNpmPackage,
  fetchurl,
  fetchzip,
  electron_41-bin,
  imagemagick,
  nodejs_24,
  python3,
  pkg-config,
  gnumake,
  gcc,
  unzip,
  ripgrep,
}:

let
  version = "26.721.41059";
  electronVersion = "42.3.0";
  electron = electron_41-bin.overrideAttrs (
    finalAttrs: _previousAttrs: {
      version = electronVersion;
      src = fetchurl {
        url = "https://github.com/electron/electron/releases/download/v${electronVersion}/electron-v${electronVersion}-${
          if stdenv.hostPlatform.isAarch64 then "linux-arm64" else "linux-x64"
        }.zip";
        hash =
          if stdenv.hostPlatform.isAarch64 then
            "sha256-Kjdf+XP7e93FOKT2eyFBlH6dclE6G6or6r7Cp/Zc0PA="
          else
            "sha256-SHpmfKanNLlYwWz/HfdNnUTSwYpszNtN1R9jAaNWxCA=";
      };
    }
  );
  electronHeaders = fetchzip {
    url = "https://artifacts.electronjs.org/headers/dist/v${electronVersion}/node-v${electronVersion}-headers.tar.gz";
    hash = "sha256-hwmsjdYUf6yFd734M3LKtZ/EIk1IDb7XwPzlt6PIBMo=";
  };
  upstreamArchive = fetchurl {
    url = "https://persistent.oaistatic.com/codex-app-prod/ChatGPT-darwin-arm64-${version}.zip";
    hash = "sha256-4rRQVvPR+KuQ9/FiSb+1pA0J0PgJnxLKDY16j9+RCM4=";
  };
  source = lib.cleanSourceWith {
    src = ./.;
    filter =
      path: type:
      let
        name = baseNameOf path;
      in
      !builtins.elem name [
        ".cache"
        "dist"
        "node_modules"
      ];
  };
in
buildNpmPackage {
  pname = "ghostship-codex-desktop-web";
  inherit version;
  src = source;

  npmDepsHash = "sha256-BA1ukjkzBMjtaZvsQPJEgFSkCRXjmtNXzgMzuZHOJdQ=";
  npmInstallFlags = [ "--ignore-scripts" ];
  dontNpmBuild = true;

  nativeBuildInputs = [
    imagemagick
    nodejs_24
    python3
    pkg-config
    gnumake
    gcc
    unzip
    ripgrep
  ];

  buildPhase = ''
    runHook preBuild

    rm -rf node_modules/electron/dist
    cp -a ${electron.dist} node_modules/electron/dist
    chmod -R u+w node_modules/electron/dist
    printf 'electron\n' > node_modules/electron/path.txt

    npm_config_nodedir=${electronHeaders} \
      npm_config_target=${electronVersion} \
      npm_config_runtime=electron \
      npm rebuild --offline --build-from-source node-pty

    mkdir -p .cache
    ln -s ${upstreamArchive} .cache/ChatGPT-darwin-arm64-${version}.zip
    node scripts/prepare-upstream.mjs \
      --release ${version} \
      --cache "$PWD/.cache" \
      --output "$PWD/prepared"

    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    cp -a prepared "$out"
    runHook postInstall
  '';

  meta = {
    description = "Versioned browser bridge for the official Codex desktop renderer";
    homepage = "https://openai.com/codex/";
    license = lib.licenses.unfree;
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
  };
}
