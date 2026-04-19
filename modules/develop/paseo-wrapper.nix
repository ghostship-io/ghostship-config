{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };

  paseo-cli = agentTooling.mkInstalledAgentWrapper {
    name = "paseo";
    binaryName = "paseo";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
  };
in
{
  environment.systemPackages = [
    paseo-cli
  ];
}
