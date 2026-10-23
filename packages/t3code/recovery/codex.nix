{
  lib,
  stdenvNoCC,
  fetchurl,
}:

let
  version = "0.163.0";
  targets = {
    aarch64-linux = {
      suffix = "linux-arm64";
      triple = "aarch64-unknown-linux-musl";
      hash = "sha512-IH2/R+4OarjGvsAf1ll3fdyLwrPgYLl3uzp6u9CyD9sj2Lw+ViDSe3QBZVHdcHJs0eIiZFg6Wprcuy4CRZaUGw==";
    };
    x86_64-linux = {
      suffix = "linux-x64";
      triple = "x86_64-unknown-linux-musl";
      hash = "sha512-uwRaOsrYogLQhcxAM/GoeWrw0QIWEMRo7c9gM8sKAviVkZQHlu9kRLJ5PkufbV+ABGjyZgIwiFdJ0LCJ0N6e8w==";
    };
  };
  target = targets.${stdenvNoCC.hostPlatform.system};
in
stdenvNoCC.mkDerivation {
  pname = "t3code-recovery-codex";
  inherit version;
  # Use the immutable upstream distribution, never the container-writable npm
  # installation. The older nixpkgs client rejects the required model at runtime.
  src = fetchurl {
    url = "https://registry.npmjs.org/@openai/codex/-/codex-${version}-${target.suffix}.tgz";
    inherit (target) hash;
  };
  sourceRoot = "package";
  dontConfigure = true;
  dontBuild = true;
  dontStrip = true;
  installPhase = ''
    runHook preInstall
    install -Dm0555 vendor/${target.triple}/bin/codex $out/bin/codex
    runHook postInstall
  '';
  meta = {
    description = "Pinned tool-free Codex recovery advisor runtime";
    homepage = "https://github.com/openai/codex";
    license = lib.licenses.asl20;
    platforms = builtins.attrNames targets;
    mainProgram = "codex";
  };
}
