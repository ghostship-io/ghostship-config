{
  pkgs,
  lib,
  inputs,
  ...
}:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };
  libsecretPath = lib.makeLibraryPath [ pkgs.libsecret ];

  gemini-cli = agentTooling.mkInstalledAgentWrapper {
    name = "gemini";
    binaryName = "gemini";
    extraEnvironment = ''
      export LD_LIBRARY_PATH="${libsecretPath}${
        if libsecretPath != "" then ":" else ""
      }''${LD_LIBRARY_PATH:-}"
    '';
    preExecHook = ''
      gemini_default_yolo=1
      gemini_waiting_for_approval_mode=0
      for arg in "$@"; do
        if [ "$gemini_waiting_for_approval_mode" -eq 1 ]; then
          gemini_default_yolo=0
          gemini_waiting_for_approval_mode=0
          continue
        fi

        case "$arg" in
          --approval-mode)
            gemini_default_yolo=0
            gemini_waiting_for_approval_mode=1
            ;;
          --approval-mode=*|--yolo|-y)
            gemini_default_yolo=0
            ;;
        esac
      done

      if [ "$gemini_default_yolo" -eq 1 ]; then
        set -- --yolo "$@"
      fi
    '';
  };
in
{
  environment.systemPackages = [
    gemini-cli
  ];
}
