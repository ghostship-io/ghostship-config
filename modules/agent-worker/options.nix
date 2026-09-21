{ lib, ... }:

{
  options.ghostship.t3Worker = {
    enable = lib.mkEnableOption "independent T3 Code worker environment";

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "User that owns the T3 Code server, projects, and credentials.";
    };

    baseDir = lib.mkOption {
      type = lib.types.str;
      default = "/home/nixos/.t3";
      description = "T3 Code data directory (T3CODE_HOME) for this environment.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 3774;
      description = "Loopback port for the T3 Code worker server.";
    };

    enableAntigravity = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Install the Antigravity ACP provider used by T3 Code.";
    };
  };
}
