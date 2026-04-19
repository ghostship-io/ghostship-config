{ ... }:

{
  imports = [
    ./agent-maintenance.nix
    ./secrets.nix
    ./gemini-wrapper.nix
    ./gemini.nix
    ./opencode-wrapper.nix
    ./paseo-wrapper.nix
    ./codex-wrapper.nix
  ];
}
