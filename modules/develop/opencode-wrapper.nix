{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };

  opencode-config = builtins.toJSON {
    "$schema" = "https://opencode.ai/config.json";
    permission = "allow";
  };

  opencode-cli = agentTooling.mkNpxAgentWrapper {
    name = "opencode";
    npmPackage = "opencode-ai";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
    preLaunchHook = agentTooling.mkOpencodeProgrammingFreeModelsHook;
  };
in
{
  environment = {
    etc."opencode/opencode.json".text = opencode-config;
    systemPackages = [
      opencode-cli
    ];
  };
}
