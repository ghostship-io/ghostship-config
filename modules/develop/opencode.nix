{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };

  opencode-config = builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    permission = "allow";
  };

  opencode-cli = agentTooling.mkInstalledAgentWrapper {
    name = "opencode";
    binaryName = "opencode";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
  };
in
{
  home.file.".config/opencode/opencode.json" = {
    text = opencode-config;
    force = true;
  };

  home.packages = [
    opencode-cli
  ];
}
