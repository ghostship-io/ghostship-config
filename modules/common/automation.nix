{ config, lib, pkgs, ... }:

let
  cfg = config.myOptions.autoUpgrade;
  agentTooling = import ../develop/agent-tooling.nix { inherit pkgs; };

  refreshPackages = lib.concatMapStringsSep "\n" (server:
    let
      package = builtins.elemAt server.args 1;
    in
    ''
      ${pkgs.nodejs}/bin/npx -y "${package}@latest" --help >/dev/null 2>&1 || true
    '') (lib.attrValues agentTooling.mcpServers);
in
{
  options.myOptions.autoUpgrade = {
    enable = lib.mkEnableOption "automated system upgrades";
  };

  config = lib.mkMerge [
    (lib.mkIf cfg.enable {
      system.autoUpgrade = {
        enable = true;
        flake = "git+ssh://git@github.com/ghostship-io/ghostship-config.git?ref=main";
        flags = [
          "--update-input" "nixpkgs"
          "--commit-lock-file"
        ];
        dates = "04:00";
        randomizedDelaySec = "45min";
        allowReboot = false;
      };
    })
    {
      system.activationScripts.agentMcpRefresh = {
        text = ''
          echo "Refreshing agent MCP packages..."
          ${refreshPackages}
        '';
      };
    }
  ];
}
