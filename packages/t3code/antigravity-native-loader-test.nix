{
  pkgs,
  package,
  guestGlibc,
  emulated,
}:
let
  guestBash = (import pkgs.path { system = "x86_64-linux"; }).bash;
in
pkgs.runCommandCC "antigravity-native-loader-test" { nativeBuildInputs = [ pkgs.patchelf ]; } ''
  mkdir runtime
  cat > harness.c <<'EOF'
  #include <unistd.h>
  int main(int argc, char **argv) {
    if (argc < 2) return 2;
    execv(argv[1], argv + 1);
    return 3;
  }
  EOF
  cat > mcp-child.c <<'EOF'
  #include <stdio.h>
  #include <string.h>
  int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "MCP child argument")) return 4;
    puts("native MCP child started");
    return 0;
  }
  EOF
  cc harness.c -o runtime/localharness_external
  cc mcp-child.c -Wl,--no-as-needed -latomic -o mcp-child
  # Downloaded T3 has no Nix RUNPATH for libatomic. Reproduce that boundary.
  patchelf --remove-rpath mcp-child
  if LD_LIBRARY_PATH=${guestGlibc}/lib ./mcp-child "MCP child argument" 2>negative.log; then
    echo 'fixture unexpectedly found libatomic without the native library path' >&2
    exit 1
  fi
  grep -F libatomic.so.1 negative.log
  export T3CODE_ANTIGRAVITY_RUNTIME="$PWD/runtime"
  ${
    if emulated then
      ''
        ${pkgs.qemu-user}/bin/qemu-x86_64 -L ${guestGlibc} \
          -E LD_LIBRARY_PATH=${guestGlibc}/lib ${guestBash}/bin/bash \
          -c 'exec "$@"' -- ${package}/bin/localharness_external \
          "$PWD/mcp-child" "MCP child argument" > result
      ''
    else
      ''
        LD_LIBRARY_PATH=${guestGlibc}/lib ${package}/bin/localharness_external \
          "$PWD/mcp-child" "MCP child argument" > result
      ''
  }
  grep -Fx 'native MCP child started' result
  cp result "$out"
''
