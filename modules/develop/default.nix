{ pkgs, ... }:

let
  agent-browser = pkgs.writeShellScriptBin "agent-browser" ''
    exec ${pkgs.nodejs}/bin/npx -y agent-browser "$@"
  '';
in
{
  environment.systemPackages = [ agent-browser ];

  imports = [
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./codex-wrapper.nix
  ];
}
