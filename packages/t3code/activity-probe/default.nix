{ pkgs }:

pkgs.stdenv.mkDerivation {
  pname = "t3code-activity-probe";
  version = "1.0.0";
  src = ./.;

  installPhase = ''
    mkdir -p $out/bin $out/libexec
    cp probe-v1-sqlite.cjs $out/libexec/
    chmod +x $out/libexec/probe-v1-sqlite.cjs

    cat > $out/bin/t3code-activity-probe <<WRAPPER
    #!${pkgs.bash}/bin/bash
    set -u
    export PATH="${pkgs.nodejs_24}/bin:\$PATH"
    ADAPTER="\''${T3CODE_ACTIVITY_PROBE_ADAPTER:-v1-sqlite}"
    DIR="$out/libexec"
    case "\$ADAPTER" in
      v1-sqlite)
        exec ${pkgs.nodejs_24}/bin/node "\$DIR/probe-v1-sqlite.cjs" "\$@"
        ;;
      v2-api)
        if [ -n "\''${T3CODE_API_URL:-}" ]; then
          exit 2
        else
          exec ${pkgs.nodejs_24}/bin/node "\$DIR/probe-v1-sqlite.cjs" "\$@"
        fi
        ;;
      *)
        echo "unknown activity probe adapter: \$ADAPTER" >&2
        exit 2
        ;;
    esac
    WRAPPER
    chmod +x $out/bin/t3code-activity-probe
  '';
}
