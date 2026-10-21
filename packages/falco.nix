# Falco runtime security from the upstream static release (nixpkgs has none),
# with the container plugin that supplies container names and images. Both
# hashes were checked against the downloads on chill-penguin on 2026-10-21.
{
  lib,
  stdenv,
  fetchurl,
  autoPatchelfHook,
}:
let
  plugin = fetchurl {
    url = "https://download.falco.org/plugins/stable/container-0.7.5-linux-aarch64.tar.gz";
    hash = "sha256-kHpU8b261Zy8E3hZxmvh8xXDVW7PQrASWS+2tYGLA3Q=";
  };
in
stdenv.mkDerivation (finalAttrs: {
  pname = "falco";
  version = "0.45.1";
  src = fetchurl {
    url = "https://download.falco.org/packages/bin/aarch64/falco-${finalAttrs.version}-aarch64.tar.gz";
    hash = "sha256-+y27B+G8qZCgZDIjnCKUY4sBvkDOK/XHoBNBjNwQNrU=";
  };
  nativeBuildInputs = [ autoPatchelfHook ];
  buildInputs = [ stdenv.cc.cc.lib ];
  sourceRoot = ".";
  unpackPhase = ''
    tar -xzf $src
    mkdir plugin && tar -xzf ${plugin} -C plugin
  '';
  installPhase = ''
    install -Dm755 falco-${finalAttrs.version}-aarch64/usr/bin/falco $out/bin/falco
    install -Dm644 -t $out/share/falco falco-${finalAttrs.version}-aarch64/etc/falco/falco_rules.yaml
    install -Dm755 plugin/libcontainer.so $out/share/falco/plugins/libcontainer.so
  '';
  meta = {
    description = "Cloud-native runtime security";
    homepage = "https://falco.org";
    license = lib.licenses.asl20;
    platforms = [ "aarch64-linux" ];
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
})
