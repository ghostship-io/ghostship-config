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

  claude-cli = agentTooling.mkInstalledAgentWrapper {
    name = "claude";
    binaryName = "claude";
    extraEnvironment = ''
      export SSH_AUTH_SOCK="/run/user/1000/ssh-agent"
    '';
  };
in
{
  environment.systemPackages = [ claude-cli ];
}
