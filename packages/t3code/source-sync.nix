{ lib, pkgs, installer, runtimeEnv ? "" }:
pkgs.writeShellScriptBin "t3code-install-ghostship-agent" ''
  set -eu
  ${runtimeEnv}
  unset LD_LIBRARY_PATH
  export HOME=/home/t3code
  export USER=t3code
  export XDG_STATE_HOME="''${XDG_STATE_HOME:-$HOME/.local/state}"
  export PATH=${lib.makeBinPath [ pkgs.coreutils pkgs.git pkgs.openssh pkgs.gh pkgs.util-linux ]}:$PATH
  export NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt
  export SSL_CERT_FILE=$NIX_SSL_CERT_FILE
  if [ "$(id -u)" = 0 ]; then
    exec ${pkgs.su-exec}/bin/su-exec 3000:3000 "$0" "$@"
  fi
  exec ${pkgs.bash}/bin/bash ${./source-sync.sh} /workspace ${installer} "$@"
''
