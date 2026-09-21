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
  baseUrl = "https://dl.google.com/agy-extensions/releases/linux/agy-acp-server-agy_acp_server_${version}-linux";
  assets = {
    x86_64-linux = {
      url = "${baseUrl}-x86_64.zip";
      sha256 = "38f62d01b32deb0907b3d39a71ec301fd36369f6ffd1cf262d4af385177f79df";
    };
    aarch64-linux = {
      url = "${baseUrl}-arm64.zip";
      sha256 = "ed69e64b308fcb123ab54bf3277bf9cb0d651064f885ea5aab0ff520c7175398";
    };
  };
  # Google's ACP server aborts natively on 16 KiB pages, so ARM64 must run the
  # x86_64 server through QEMU (whose x86 guest has fixed 4 KiB pages). The
  # harness is a static Go binary with no page-size assumption: emulating it
  # corrupts its runtime and panics mid-turn, so it runs natively on ARM64.
  emulated = stdenvNoCC.hostPlatform.isAarch64;
  serverArchive = fetchurl assets.x86_64-linux;
  harnessArchive = fetchurl (if emulated then assets.aarch64-linux else assets.x86_64-linux);
  # QEMU's x86 target has fixed 4 KiB pages. Its ARM target inherits the host
  # page size, so ARM emulation cannot run Google's allocator on Asahi either.
  guestGlibc =
    if emulated then (import pkgs.path { system = "x86_64-linux"; }).glibc else glibc;
in
stdenvNoCC.mkDerivation {
  pname = "antigravity-acp";
  inherit version;
  dontUnpack = true;
  dontFixup = true;
  nativeBuildInputs = [ unzip ];
  installPhase = ''
    mkdir -p "$out/bin" "$out/libexec"
    unzip -j ${serverArchive} agy_acp_server.par -d "$out/libexec"
    unzip -j ${harnessArchive} localharness_external -d "$out/libexec"
    chmod 0755 "$out/libexec/agy_acp_server.par" "$out/libexec/localharness_external"
    cat > "$out/libexec/agy_acp-launch" <<EOF
    #!${runtimeShell}
    set -eu
    runtime="\''${T3CODE_ANTIGRAVITY_RUNTIME:-\''${XDG_DATA_HOME:-\$HOME/.local/share}/t3code-tools/antigravity/current}"
    if [ ! -x "\$runtime/agy_acp_server.par" ]; then
      runtime="$out/libexec"
    fi
    ${
      lib.optionalString emulated ''
        exec ${qemu-user}/bin/qemu-x86_64 -L ${guestGlibc} -E LD_LIBRARY_PATH=${guestGlibc}/lib \
          "\$runtime/agy_acp_server.par" "\$@"
      ''
    }
    exec "\$runtime/agy_acp_server.par" "\$@"
    EOF
    install -m0755 ${./antigravity-acp-proxy.py} "$out/libexec/antigravity-acp-proxy.py"
    cat > "$out/bin/agy_acp_server.par" <<EOF
    #!${runtimeShell}
    set -eu
    # T3 sanitizes provider child environments, including this variable.  The
    # ACP server nevertheless needs its helper forced through our native
    # wrapper on ARM64: otherwise it discovers the staged x86_64 helper and
    # QEMU crashes it during session startup.
    export ANTIGRAVITY_HARNESS_PATH="$out/bin/localharness_external"
    export T3CODE_ANTIGRAVITY_LAUNCHER="$out/libexec/agy_acp-launch"
    export T3CODE_ANTIGRAVITY_VERSION="${version}"
    exec ${pkgs.python3}/bin/python3 "$out/libexec/antigravity-acp-proxy.py" "\$@"
    EOF
    cat > "$out/bin/localharness_external" <<EOF
    #!${runtimeShell}
    set -eu
    runtime="\''${T3CODE_ANTIGRAVITY_RUNTIME:-\''${XDG_DATA_HOME:-\$HOME/.local/share}/t3code-tools/antigravity/current}"
    harness="\$runtime/localharness_external"
    ${
      lib.optionalString emulated ''
        # Never emulate the harness. Use a managed runtime harness only when it
        # is already ARM64 (e_machine 183); otherwise fall back to the bundled
        # native binary. This also migrates a runtime staged before the fix.
        if [ ! -x "\$harness" ] \
          || [ "\$(${pkgs.coreutils}/bin/od -An -j18 -N1 -tu1 "\$harness" 2>/dev/null | ${pkgs.coreutils}/bin/tr -d '[:space:]')" != "183" ]; then
          harness="$out/libexec/localharness_external"
        fi
      ''
    }
    if [ ! -x "\$harness" ]; then
      harness="$out/libexec/localharness_external"
    fi
    exec "\$harness" "\$@"
    EOF
    chmod 0755 "$out/bin/agy_acp_server.par" "$out/bin/localharness_external" "$out/libexec/agy_acp-launch"
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
