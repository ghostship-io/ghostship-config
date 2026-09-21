{ lib, ... }:

{
  options.ghostship.t3Worker = {
    enable = lib.mkEnableOption "independent T3 Code worker environment";

    user = lib.mkOption {
      type = lib.types.enum [ "nixos" ];
      default = "nixos";
      description = "User that owns the T3 Code server, projects, credentials, and managed CLI installation.";
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

    directTunnel = {
      enable = lib.mkEnableOption "dedicated Cloudflare tunnel for direct T3 clients";

      hostname = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "Stable HTTPS hostname routed to this worker's loopback server.";
      };

      tokenFile = lib.mkOption {
        type = lib.types.str;
        default = "/home/nixos/.t3/cloudflare-tunnel-token";
        description = "Persistent Cloudflare connector token file, kept outside the Nix store.";
      };

    };
  };
}
