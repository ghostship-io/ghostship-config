{
  pkgs,
  lib,
  stdenvNoCC,
  fetchurl,
  unzip,
  qemu-user,
  glibc,
  runtimeShell,
}:
let
  # Official ACP registry release, also pinned by upstream T3 Code.
  version = "1.1.1";
  # QEMU's x86 target has fixed 4 KiB pages. Its ARM target inherits the host
  # page size, so ARM emulation cannot run Google's allocator on Asahi either.
  guestGlibc =
    if stdenvNoCC.hostPlatform.isAarch64 then
      (import pkgs.path { system = "x86_64-linux"; }).glibc
    else
      glibc;
in
stdenvNoCC.mkDerivation {
  pname = "antigravity-acp";
  inherit version;
  src = fetchurl {
    url = "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-agy_acp_server_${version}-linux-x86_64.zip";
    sha256 = "38f62d01b32deb0907b3d39a71ec301fd36369f6ffd1cf262d4af385177f79df";
  };
  nativeBuildInputs = [ unzip ];
  dontUnpack = true;
  dontFixup = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/libexec"
    unzip -j "$src" agy_acp_server.par localharness_external -d "$out/libexec"
    chmod 0755 "$out/libexec/agy_acp_server.par" "$out/libexec/localharness_external"
    for executable in agy_acp_server.par localharness_external; do
      cat > "$out/bin/$executable" <<EOF
    #!${runtimeShell}
    set -eu
    runtime="\''${T3CODE_ANTIGRAVITY_RUNTIME:-\''${XDG_DATA_HOME:-\$HOME/.local/share}/t3code-tools/antigravity/current}"
    if [ ! -x "\$runtime/$executable" ]; then
      runtime="$out/libexec"
    fi
    ${lib.optionalString stdenvNoCC.hostPlatform.isAarch64 ''
      exec ${qemu-user}/bin/qemu-x86_64 -L ${guestGlibc} -E LD_LIBRARY_PATH=${guestGlibc}/lib "\$runtime/$executable" "\$@"
    ''}
    exec "\$runtime/$executable" "\$@"
    EOF
      chmod 0755 "$out/bin/$executable"
    done
  '';
  meta = {
    description = "Official Google Antigravity ACP agent for the T3 Code container";
    homepage = "https://github.com/agentclientprotocol/registry/tree/main/antigravity-acp";
    license = lib.licenses.unfree;
    platforms = [
      "x86_64-linux"
      "aarch64-linux"
    ];
  };
}
