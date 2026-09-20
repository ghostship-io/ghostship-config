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

  cursor-cli = agentTooling.mkInstalledAgentWrapper {
    name = "cursor";
    binaryName = "cursor";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
  };
in
{
  environment.systemPackages = [ cursor-cli ];
}
