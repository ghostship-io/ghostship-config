{ pkgs }:

pkgs.stdenv.mkDerivation {
  pname = "t3code-activity-probe";
  version = "1.0.0";
  src = ./.;

  installPhase = ''
    mkdir -p $out/bin $out/libexec
    cp probe-v1-sqlite.cjs probe-v2-sqlite.cjs $out/libexec/
    chmod +x $out/libexec/probe-v1-sqlite.cjs $out/libexec/probe-v2-sqlite.cjs

    cat > $out/bin/t3code-activity-probe <<WRAPPER
    #!${pkgs.bash}/bin/bash
    set -u
    export PATH="${pkgs.nodejs_24}/bin:\$PATH"
    ADAPTER="\''${T3CODE_ACTIVITY_PROBE_ADAPTER:-auto}"
    DIR="$out/libexec"
    STATE="\''${T3CODE_STATE_DB:-\''${T3CODE_HOME:+\$T3CODE_HOME/userdata/state.sqlite}}"
    STATE="\''${STATE:-\$HOME/.t3/userdata/state.sqlite}"
    # T3 Code 2 migrates state.sqlite into statev2.sqlite beside it.
    V2="\$(dirname "\$STATE")/statev2.sqlite"
    if [ "\$ADAPTER" = auto ]; then
      if [ -f "\$V2" ]; then ADAPTER=v2-sqlite; else ADAPTER=v1-sqlite; fi
    fi
    case "\$ADAPTER" in
      v1-sqlite)
        exec ${pkgs.nodejs_24}/bin/node "\$DIR/probe-v1-sqlite.cjs" "\$@"
        ;;
      v2-sqlite)
        T3CODE_STATE_DB="\$V2" exec ${pkgs.nodejs_24}/bin/node "\$DIR/probe-v2-sqlite.cjs" "\$@"
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
