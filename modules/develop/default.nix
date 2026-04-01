{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };
in
{
  environment.systemPackages = [
    agentTooling.agentBrowser
    agentTooling.openspecCli
  ];

  imports = [
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./codex-wrapper.nix
  ];
}
