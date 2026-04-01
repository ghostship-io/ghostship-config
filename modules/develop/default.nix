{ pkgs, ... }:

let
  agentTooling = import ./agent-tooling.nix { inherit pkgs; };
in
{
  environment.systemPackages = [ agentTooling.agentBrowser ];

  imports = [
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./codex-wrapper.nix
  ];
}
