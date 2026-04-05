{ pkgs, inputs, ... }:

let
  agentTooling = import ./agent-tooling.nix {
    inherit pkgs inputs;
  };
in
{
  environment.systemPackages = [
    agentTooling.agentBrowser
    agentTooling.agentMaintenance
    agentTooling.openspecCli
  ];

  imports = [
    ./agent-maintenance.nix
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./codex-wrapper.nix
  ];
}
