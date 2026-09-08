{
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
}:
let
  # Official ACP registry release, also pinned by upstream T3 Code.
  version = "1.1.1";
  assets = {
    x86_64-linux = {
      arch = "x86_64";
      sha256 = "38f62d01b32deb0907b3d39a71ec301fd36369f6ffd1cf262d4af385177f79df";
    };
    aarch64-linux = {
      arch = "arm64";
      sha256 = "ed69e64b308fcb123ab54bf3277bf9cb0d651064f885ea5aab0ff520c7175398";
    };
  };
  asset = assets.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation {
  pname = "antigravity-acp";
  inherit version;
  src = fetchurl {
    url = "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-agy_acp_server_${version}-linux-${asset.arch}.zip";
    inherit (asset) sha256;
  };
  nativeBuildInputs = [ unzip ];
  dontUnpack = true;
  dontFixup = true;
  installPhase = ''
    mkdir -p "$out/bin"
    unzip -j "$src" agy_acp_server.par localharness_external -d "$out/bin"
    chmod 0755 "$out/bin/agy_acp_server.par" "$out/bin/localharness_external"
  '';
  meta = {
    description = "Official Google Antigravity ACP agent for the T3 Code container";
    homepage = "https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp";
    license = lib.licenses.unfree;
    platforms = builtins.attrNames assets;
  };
}
